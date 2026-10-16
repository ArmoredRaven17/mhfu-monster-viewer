"""Drop the animation keys that linear interpolation already reproduces.

    python reduce-keys.py <glb> [...]        # in place, prints the saving
    python reduce-keys.py --dry <glb>        # report only
    from reduce_keys import fix; fix(path)   # what harvest-monsters.py calls

WHY there is anything to drop. The source LMT stores each track's own sparse keys, each with
its own frame delta, and `lmt_to_gltf` RESAMPLES them: measured on Rathian's list 0, the LMT
holds 71,729 rotation keys and the exported glb holds 135,874 for the same 4,312 frames --
1.89x, at up to 60 keys per second per channel. That resampling, not the int16 quantisation,
is why an exported list is 2.1-3.2x its LMT. Fitting a curve back to the sparse original is
not needed: dropping a key whose value the straight line between its neighbours already
gives, to a stated tolerance, is exact where the exporter was redundant and bounded
everywhere else.

The pass is per sampler:
  * a key survives if removing it would move the interpolated value at its own time by more
    than the tolerance -- rotation as an ANGLE between quaternions, translation as a distance
    in the file's own units. Decisions are made against the ORIGINAL curve, not the thinned
    one, so error cannot accumulate ALONG A TRACK. It does accumulate DOWN A BONE CHAIN,
    which is what the tolerances below are calibrated against.
  * first and last keys are always kept, so a clip's duration never changes.
  * a sampler whose values are all equal collapses to one key.
  * identical time arrays are shared between samplers afterwards (they were 514 distinct
    accessors for 1,512 samplers on Rathian's list 0; sharing costs nothing and the JSON
    chunk is a third of a stripped file).
Component types are preserved: rotations stay normalized int16, translations float32.

The reported worst-case error is the real one: the maximum angle / distance between the
original curve and the reduced one, sampled at every original key time. Run it ONCE per file
(harvest-monsters.py does): a second pass measures against the already-thinned curve, so it
finds a little more to drop (98% on a re-run) and the errors would add up run over run.
"""
import argparse
import json
import math
import os
import struct
import sys

# CALIBRATED against world-space error, not joint angle (2026-09-04, Rathian's list 0 played
# in three.js against the converter's own output, 36 clips sampled 30 times each, every bone
# compared). A per-joint angle tolerance compounds down a chain: the worst case is ALWAYS the
# tail tip, bone 145, six joints out.
#
#     tolerance   file        worst bone error   p95
#     none        1.67 MB     0                  0
#     0.05 deg    1.26 MB     11.6 mm            0.8 mm
#     0.10 deg    1.20 MB     27.6 mm            4.1 mm
#     0.25 deg    0.96 MB     91 mm              14.5 mm
#
# 0.05 keeps the worst case near a centimetre on a 5 m monster and still saves a quarter of
# the bytes; 0.25 put a Rathian's tail tip 9 cm off in a tail swipe, which is what this app
# exists to look at. Whole library: 487 MB of motions rather than 645 unreduced.
ROT_TOL_DEG = 0.05
POS_TOL = 0.0005         # metres at the viewer's scale (the glb divides the ROM's cm by 100)

CT = {5126: ("f", 4), 5122: ("h", 2), 5123: ("H", 2), 5120: ("b", 1), 5121: ("B", 1)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(path):
    b = open(path, "rb").read()
    if b[:4] != b"glTF":
        raise ValueError("not a glb: " + path)
    total = struct.unpack_from("<I", b, 8)[0]
    off, js, bin_ = 12, None, b""
    while off < total:
        ln, typ = struct.unpack_from("<I4s", b, off)
        data = b[off + 8:off + 8 + ln]
        if typ == b"JSON":
            js = json.loads(data)
        elif typ == b"BIN\0":
            bin_ = data
        off += 8 + ln
    return js, bin_


def write_glb(path, js, bin_):
    j = json.dumps(js, separators=(",", ":")).encode("utf-8")
    j += b" " * (-len(j) % 4)
    b = bytes(bin_) + b"\0" * (-len(bin_) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<I4s", len(j), b"JSON") + j)
        f.write(struct.pack("<I4s", len(b), b"BIN\0") + b)
    os.replace(tmp, path)


def read_accessor(js, bin_, idx):
    """[[component, ...], ...] as floats; normalized integers are decoded to their real range."""
    a = js["accessors"][idx]
    n, ct = NCOMP[a["type"]], a["componentType"]
    fmt, size = CT[ct]
    bv = js["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or n * size
    norm = a.get("normalized", False)
    scale = {5122: 32767.0, 5121: 255.0, 5120: 127.0, 5123: 65535.0}.get(ct, 1.0) if norm else 1.0
    out = []
    for i in range(a["count"]):
        vals = struct.unpack_from("<%d%s" % (n, fmt), bin_, base + i * stride)
        out.append([max(-1.0, v / scale) if norm else float(v) for v in vals])
    return out, a


def pack_values(rows, ct):
    fmt, _size = CT[ct]
    scale = {5122: 32767.0, 5121: 255.0, 5120: 127.0, 5123: 65535.0}.get(ct, 1.0)
    buf = bytearray()
    for r in rows:
        if ct == 5126:
            buf += struct.pack("<%df" % len(r), *r)
        else:
            buf += struct.pack("<%d%s" % (len(r), fmt), *[int(round(max(-1.0, min(1.0, v)) * scale)) for v in r])
    return bytes(buf)


def _lerp_at(times, values, lo, hi, t):
    """the value the straight line from key `lo` to key `hi` gives at time t"""
    span = times[hi][0] - times[lo][0]
    u = 0.0 if span <= 0 else (t - times[lo][0]) / span
    return [values[lo][k] + (values[hi][k] - values[lo][k]) * u for k in range(len(values[lo]))]


def _quat_angle(a, b):
    """angle in degrees between two quaternions, sign-insensitive"""
    d = abs(sum(x * y for x, y in zip(a, b)))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return math.degrees(2.0 * math.acos(max(0.0, min(1.0, d / (na * nb)))))


def _err(path, a, b):
    if path == "rotation":
        return _quat_angle(a, b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def reduce_sampler(times, values, path, rot_tol, pos_tol):
    """indices of the keys to keep. Greedy from the left, always measured against the
    ORIGINAL values, so the error is bounded by the tolerance at every original key."""
    n = len(values)
    if n <= 2:
        return list(range(n))
    tol = rot_tol if path == "rotation" else pos_tol
    if all(_err(path, values[i], values[0]) <= tol for i in range(1, n)):
        return [0, n - 1]                     # constant track: the two ends carry it
    keep = [0]
    lo = 0
    i = 1
    while i < n - 1:
        # can the segment lo..i+1 stand in for every key strictly between them?
        hi = i + 1
        ok = True
        for k in range(lo + 1, hi):
            if _err(path, _lerp_at(times, values, lo, hi, times[k][0]), values[k]) > tol:
                ok = False
                break
        if ok:
            i += 1
        else:
            keep.append(i)
            lo = i
            i += 1
    keep.append(n - 1)
    return keep


def fix(path, rot_tol=ROT_TOL_DEG, pos_tol=POS_TOL, dry=False):
    js, bin_ = read_glb(path)
    if not js.get("animations"):
        return None
    before_keys = after_keys = 0
    worst = {"rotation": 0.0, "translation": 0.0, "scale": 0.0}
    # sampler index (per animation) -> the rows to write
    plan = []
    for ai, anim in enumerate(js["animations"]):
        target = {}
        for c in anim["channels"]:
            target[c["sampler"]] = c["target"]["path"]
        for si, s in enumerate(anim["samplers"]):
            tpath = target.get(si, "translation")
            times, tacc = read_accessor(js, bin_, s["input"])
            values, vacc = read_accessor(js, bin_, s["output"])
            before_keys += len(values)
            keep = reduce_sampler(times, values, tpath, rot_tol, pos_tol)
            after_keys += len(keep)
            # the real error of the result, measured at every original key time
            if len(keep) < len(values):
                for k in range(len(values)):
                    j = 0
                    while j + 1 < len(keep) and keep[j + 1] < k:
                        j += 1
                    lo, hi = keep[j], keep[min(j + 1, len(keep) - 1)]
                    if lo == k or hi == k:
                        continue
                    e = _err(tpath, _lerp_at(times, values, lo, hi, times[k][0]), values[k])
                    if e > worst.get(tpath, 0.0):
                        worst[tpath] = e
            plan.append((ai, si, tpath, [times[i] for i in keep], [values[i] for i in keep],
                         js["accessors"][s["output"]]["componentType"],
                         js["accessors"][s["output"]]["type"]))
    if dry or after_keys == before_keys:
        return {"keysBefore": before_keys, "keysAfter": after_keys,
                "maxRotDeg": round(worst["rotation"], 4), "maxPosM": round(worst["translation"], 6),
                "bytesBefore": os.path.getsize(path), "bytesAfter": os.path.getsize(path)}
    # Rebuild. ONE bufferView for the whole file, with the accessors carrying byteOffset:
    # after the reduction the JSON chunk is the larger half of a stripped list, and a view per
    # accessor was 2,746 of them on one Rathian list (~200 KB of JSON) saying nothing an
    # offset does not. Offsets are padded to 4, which satisfies glTF's alignment for both the
    # float times and the int16 rotations. Time accessors are shared between samplers whose
    # key times are identical, which many are.
    out = bytearray()
    accessors = []
    time_cache = {}

    def add_bytes(data):
        while len(out) % 4:
            out.append(0)
        at = len(out)
        out.extend(data)
        return at

    def add_times(ts):
        key = tuple(round(t[0], 7) for t in ts)
        if key in time_cache:
            return time_cache[key]
        at = add_bytes(pack_values(ts, 5126))
        accessors.append({"bufferView": 0, "byteOffset": at, "componentType": 5126,
                          "count": len(ts), "type": "SCALAR", "min": [min(key)], "max": [max(key)]})
        time_cache[key] = len(accessors) - 1
        return time_cache[key]

    for ai, si, tpath, ts, vs, ct, vtype in plan:
        ti = add_times(ts)
        at = add_bytes(pack_values(vs, ct))
        acc = {"bufferView": 0, "byteOffset": at, "componentType": ct, "count": len(vs), "type": vtype}
        if ct != 5126:
            acc["normalized"] = True
        accessors.append(acc)
        s = js["animations"][ai]["samplers"][si]
        s["input"], s["output"] = ti, len(accessors) - 1
        # LINEAR is glTF's default, and after the reduction the JSON chunk is the larger half
        # of the file (1,512 samplers on one Rathian list), so the redundant key comes out.
        s.pop("interpolation", None)
    js["accessors"] = accessors
    js["bufferViews"] = [{"buffer": 0, "byteOffset": 0, "byteLength": len(out)}]
    js["buffers"] = [{"byteLength": len(out)}]
    for n in js.get("nodes", []):
        n.pop("mesh", None)
        n.pop("skin", None)
    js.pop("meshes", None)
    js.pop("skins", None)
    js.pop("materials", None)
    before_bytes = os.path.getsize(path)
    write_glb(path, js, out)
    return {"keysBefore": before_keys, "keysAfter": after_keys,
            "maxRotDeg": round(worst["rotation"], 4), "maxPosM": round(worst["translation"], 6),
            "bytesBefore": before_bytes, "bytesAfter": os.path.getsize(path)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("glb", nargs="+")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rot", type=float, default=ROT_TOL_DEG, help="rotation tolerance, degrees")
    ap.add_argument("--pos", type=float, default=POS_TOL, help="translation tolerance, model units")
    a = ap.parse_args()
    tot_b = tot_a = 0
    for p in a.glb:
        r = fix(p, a.rot, a.pos, a.dry)
        if not r:
            print("%-40s no animations" % os.path.basename(p))
            continue
        tot_b += r["bytesBefore"]
        tot_a += r["bytesAfter"]
        print("%-40s keys %7d -> %7d (%4.1f%%)  %6.2f -> %6.2f MB  worst rot %.3f deg, pos %.4f m" % (
            os.path.basename(p), r["keysBefore"], r["keysAfter"],
            100.0 * r["keysAfter"] / max(1, r["keysBefore"]),
            r["bytesBefore"] / 1e6, r["bytesAfter"] / 1e6, r["maxRotDeg"], r["maxPosM"]))
    if len(a.glb) > 1:
        print("total %.1f -> %.1f MB (%.0f%%)" % (tot_b / 1e6, tot_a / 1e6, 100.0 * tot_a / max(1, tot_b)))
