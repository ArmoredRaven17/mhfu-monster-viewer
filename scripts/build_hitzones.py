r"""Build docs/hitzones.json and docs/hitzones/<id>.bin -- the Hit Zones panel's data -- from MHFU's own tables.

    python C:\MHFU-Extract\tools\hitzones.py     # the game's tables -> C:\MHFU-Extract\conv\monster\hitzones.json
    python scripts/build_hitzones.py             # every monster in docs/monsters.json
    python scripts/build_hitzones.py --dry       # report only

The damage tables and capsules are C:\MHFU-Extract\tools\hitzones.py's, read from the game (its header has every
field and the address the game reads it at; `--check` replays the game's capsule routine over a save state). The
FILE CONTRACT and the BAKE are the MHGU Monster Viewer's (C:\MHGU-Extract\build-hitzones.py), as in the MH4U
Monster Viewer's builder, so the page's Hit Zones panel -- GU's -- reads it:

  bin        u32 primCount, primCount x u32 vertexCount, then two equal blocks of one byte per vertex in primitive
             order: the damage slot, then the part. Primitives are the glb's in file order, as the page counts them.
  the bake   GU's viewer rule, not the game's: a drawn vertex takes the smallest capsule containing it that hangs off
             the bone it is most weighted to, else the smallest capsule containing it, else the nearest surface.
             Capsule = boneWorld @ (point / 100), radius / 100, in the bind pose (glb node "k:k" is the game's joint
             k: hitzones.py --check).
  capsules   [slot, part, shape, boneA, boneB, radius, ax, ay, az, bx, by, bz], every capsule the game tests, in game
             units. Shape 0 sphere, 1 capsule on one bone (boneB = boneA), as GU numbers them.
  capsuleFlags   the capsule's flag word (bytes +8..+B), MHFU's own bits (hitzones.py FLAGS); the page's
             zoneNeverCounted / zoneSpecialOnly read them.
  capsuleSever   the tail-cut mask of the 0x7D gate covering the capsule (0: none): it is not tested once the tail is cut.
  candidates for the bake: no NEVER, SPECIAL or CONDITIONAL bit (GU leaves conditional shapes out too), shape 0-1.
  tables / tableNames / tableNotes   one per table in the species' list, in the game's order: table k is the one the
             hit code reads while entity+0x481 = k. Each class sets it in its own code (writers in hitzones.py); the
             states are not decoded, so tables after the first are "State k" until named in TABLE_LABELS.
The tenth column of GU's contract (exhaust) does not exist in MHFU: a row is nine values.
"""
import collections, json, os, re, struct, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DOCS = os.path.join(ROOT, 'docs')
OUTDIR = os.path.join(DOCS, 'hitzones')
OUTJSON = os.path.join(DOCS, 'hitzones.json')
SOURCE = r'C:\MHFU-Extract\conv\monster\hitzones.json'
DRY = '--dry' in sys.argv
CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
# Names for the tables after the first, by (species, table index): Raven's to give.
TABLE_LABELS = {}


# ---- glb helpers (the GU builder's) -------------------------------------------------------------------------------
def glb_split(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'glTF', path
    off, js, bin_ = 12, None, b''
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off)
        chunk = d[off + 8: off + 8 + ln]
        if ty == 0x4E4F534A: js = json.loads(chunk.decode('utf-8'))
        elif ty == 0x004E4942: bin_ = chunk
        off += 8 + ln
    return js, bin_


def acc_raw(js, bin_, i):
    a = js['accessors'][i]
    bv = js['bufferViews'][a['bufferView']]
    fmt, sz = CT[a['componentType']]
    n = NC[a['type']]
    stride = bv.get('byteStride') or sz * n
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    if stride == sz * n:
        return np.frombuffer(bin_, dtype=np.dtype('<' + fmt), count=a['count'] * n, offset=base).reshape(-1, n)
    out = np.empty((a['count'], n), dtype=np.dtype('<' + fmt))
    for k in range(a['count']):
        out[k] = struct.unpack_from('<%d%s' % (n, fmt), bin_, base + k * stride)
    return out


def node_world_all(js):
    par = {}
    for i, nd in enumerate(js['nodes']):
        for c in nd.get('children', []): par[c] = i

    def local(i):
        nd = js['nodes'][i]
        if 'matrix' in nd:
            return np.array(nd['matrix'], float).reshape(4, 4).T
        M = np.eye(4)
        x, y, z, w = nd.get('rotation', [0, 0, 0, 1])
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)
        M[:3, :3] = R @ np.diag(nd.get('scale', [1, 1, 1]))
        M[:3, 3] = nd.get('translation', [0, 0, 0])
        return M

    out = {}
    for i in range(len(js['nodes'])):
        M, k, chain = np.eye(4), i, []
        while k is not None:
            chain.append(k); k = par.get(k)
        for k in reversed(chain): M = M @ local(k)
        out[i] = M
    return out


def bind_matrix(js, bin_, world):
    sk = js['skins'][0]
    raw = acc_raw(js, bin_, sk['inverseBindMatrices']).astype(np.float64)
    ibm = raw.reshape(-1, 4, 4).transpose(0, 2, 1)
    Ms = np.array([world[n] @ ibm[k] for k, n in enumerate(sk['joints'])])
    return Ms.mean(0), float(np.abs(Ms - Ms[0]).max())


def bone_world(js, world):
    """Joint k's bind-pose world matrix: the bone node "k:k" (render/monster.js hangs a capsule on its leaf, which
    sits on it with no offset)."""
    out = {}
    for i, nd in enumerate(js['nodes']):
        m = re.match(r'^(\d+):(\d+)$', nd.get('name', '') or '')
        if m: out[int(m.group(2))] = world[i]
    return out


def joint_gids(js):
    out = []
    for nd in js['skins'][0]['joints']:
        m = re.match(r'^(\d+):(\d+)', js['nodes'][nd].get('name', '') or '')
        out.append(int(m.group(2)) if m else -1)
    return np.array(out)


def game_units(x):
    v = round(float(x), 3)
    return int(v) if v == int(v) else v


def capsule_world(c, bw):
    s = 0.01
    if c['shape'] not in (0, 1): return None
    M = np.eye(4) if c['space'] == 'model' else bw.get(c['bone'])
    if M is None: return None
    pa = (M @ np.append(np.array(c['a']) * s, 1.0))[:3]
    pb = pa if c['shape'] == 0 else (M @ np.append(np.array(c['b']) * s, 1.0))[:3]
    return pa, pb, c['radius'] * s


def nearest_slot(P, caps, dom):
    """GU's rule (its build-hitzones.py nearest_slot): same-bone smallest containing, else smallest containing,
    else nearest surface."""
    best = np.full(len(P), np.inf)
    slot = np.zeros(len(P), dtype=np.uint8); part = np.zeros(len(P), dtype=np.uint8)
    in_r = np.full(len(P), np.inf)
    in_slot = np.zeros(len(P), dtype=np.uint8); in_part = np.zeros(len(P), dtype=np.uint8)
    same_r = np.full(len(P), np.inf)
    same_slot = np.zeros(len(P), dtype=np.uint8); same_part = np.zeros(len(P), dtype=np.uint8)
    for pa, pb, r, sl, pt, bone in caps:
        ab = pb - pa
        L2 = float(ab @ ab)
        if L2 < 1e-12:
            d = np.linalg.norm(P - pa, axis=1) - r
        else:
            t = np.clip(((P - pa) @ ab) / L2, 0.0, 1.0)[:, None]
            d = np.linalg.norm(P - (pa + t * ab), axis=1) - r
        hit = d < best
        best[hit] = d[hit]; slot[hit] = sl; part[hit] = pt
        inside = (d < 0) & (r < in_r)
        in_r[inside] = r; in_slot[inside] = sl; in_part[inside] = pt
        if dom is not None and bone is not None:
            own = (d < 0) & (dom == bone) & (r < same_r)
            same_r[own] = r; same_slot[own] = sl; same_part[own] = pt
    held = np.isfinite(in_r)
    slot[held] = in_slot[held]; part[held] = in_part[held]
    own = np.isfinite(same_r)
    slot[own] = same_slot[own]; part[own] = same_part[own]
    return slot, part, best


def bake(e, d, gates, stats):
    js, bin_ = glb_split(os.path.join(DOCS, e['glb']))
    if 'skins' not in js:
        stats['unskinned'] += 1
        return None, None
    world = node_world_all(js)
    M, spread = bind_matrix(js, bin_, world)
    if spread > 1e-4:
        stats['not in bind pose'] += 1
        return None, None
    bw = bone_world(js, world)
    caps = []
    for c in d['capsules']:
        if c['flags'] & gates['never']: stats['capsule never counted'] += 1; continue
        if c['flags'] & gates['special']: stats['capsule only for particular attacks'] += 1; continue
        if c['flags'] & gates['conditional']: stats['capsule only in a monster state'] += 1; continue
        w = capsule_world(c, bw)
        if w is None: stats['capsule unplaceable'] += 1; continue
        caps.append((w[0], w[1], w[2], c['slot'], c['part'], c['bone']))
    if not caps:
        stats['no capsule placed'] += 1
        return None, None
    gid = joint_gids(js)
    hide = set(e.get('hideIdx') or [])
    prims, blobs, pblobs, n, diag = [], [], [], 0, None
    for me in js.get('meshes', []):
        for pr in me['primitives']:
            if n in hide:
                n += 1; continue
            a = js['accessors'][pr['attributes']['POSITION']]
            raw = acc_raw(js, bin_, pr['attributes']['POSITION']).astype(np.float64)
            if a.get('normalized'): raw = raw / 32767.0
            P = (M @ np.hstack([raw, np.ones((len(raw), 1))]).T).T[:, :3]
            if diag is None:
                diag = float(np.linalg.norm(P.max(0) - P.min(0))) or 1.0
            dom = None
            if 'JOINTS_0' in pr['attributes'] and 'WEIGHTS_0' in pr['attributes']:
                J = acc_raw(js, bin_, pr['attributes']['JOINTS_0']).astype(np.int64)
                Wt = acc_raw(js, bin_, pr['attributes']['WEIGHTS_0']).astype(np.float64)
                dom = gid[J[np.arange(len(J)), np.argmax(Wt, axis=1)]]
            sl, pt, dist = nearest_slot(P, caps, dom)
            stats['vertices'] += len(P)
            stats['vertices far (>5% of the model outside every capsule)'] += int((dist > 0.05 * diag).sum())
            prims.append((n, len(P)))
            blobs.append(sl.tobytes()); pblobs.append(pt.tobytes())
            n += 1
    blob = struct.pack('<I', len(prims)) + b''.join(struct.pack('<I', c) for _, c in prims)
    blob += b''.join(blobs) + b''.join(pblobs)
    never = gates['never']
    rec = {'prims': [p for p, _ in prims], 'slotsUsed': sorted({int(x) for s in blobs for x in s}),
           'partsUsed': sorted({int(x) for s in pblobs for x in s}),
           'slotsDefined': sorted({c['slot'] for c in d['capsules'] if not c['flags'] & never})}
    return rec, blob


def main():
    mon = json.load(open(os.path.join(DOCS, 'monsters.json'), encoding='utf-8'))['monsters']
    src = json.load(open(SOURCE))
    cols = src['_about']['columns']
    gates = {k: src['_about'][k] for k in ('never', 'special', 'conditional')}
    stats = collections.Counter()
    out = {'_about': {'source': 'C:\\MHFU-Extract\\tools\\hitzones.py (MHFU code, addresses in its header); bake and '
                                'contract: the MHGU Monster Viewer build-hitzones.py; see scripts/build_hitzones.py',
                      'types': cols, 'flags': src['_about']['flags'],
                      'never': gates['never'], 'special': gates['special'], 'conditional': gates['conditional']},
           'monsters': {}}
    blobs = {}
    for e in mon:
        s = int(e['em'][2:])
        d = src['species'].get(str(s))
        if not d or not d['capsules']:
            stats['no capsules (%s)' % e['id']] += 1
            continue
        rec, blob = bake(e, d, gates, stats)
        if rec is None:
            continue
        n = len(d['tables'])
        rec.update({
            'bin': 'hitzones/%s.bin' % e['id'],
            'tables': [[dict(zip(cols, row)) for row in t] for t in d['tables']],
            'tableNames': ['Default'] + [TABLE_LABELS.get((s, k), 'State %d' % k) for k in range(1, n)],
            'tableNotes': [''] + ['The table the hit code reads while entity+0x481 = %d (the class sets it in its own '
                                  'code; the state is not decoded yet). Species record %s +0xAC.' % (k, d['record'])
                                  for k in range(1, n)],
            'capsules': [[c['slot'], c['part'], c['shape'], c['bone'] if c['bone'] is not None else -1,
                          c['bone'] if c['bone'] is not None else -1, game_units(c['radius'])]
                         + [game_units(x) for x in c['a']] + [game_units(x) for x in c['b']] for c in d['capsules']],
            'capsuleFlags': [c['flags'] for c in d['capsules']],
            'capsuleSever': [c['sever'] for c in d['capsules']],
        })
        out['monsters'][e['id']] = rec
        blobs[e['id']] = blob
        stats['tables: %d' % n] += 1
    print('monsters baked', len(out['monsters']), 'of', len(mon))
    for k, v in sorted(stats.items()):
        print('  %-58s %d' % (k, v))
    if stats['vertices']:
        print('  far share %.2f%%' % (100.0 * stats['vertices far (>5% of the model outside every capsule)']
                                      / stats['vertices']))
    if DRY:
        print('dry run: nothing written'); return
    os.makedirs(OUTDIR, exist_ok=True)
    for hid, blob in blobs.items():
        open(os.path.join(OUTDIR, hid + '.bin'), 'wb').write(blob)
    json.dump(out, open(OUTJSON, 'w', encoding='utf-8'), separators=(',', ':'))
    tot = os.path.getsize(OUTJSON) + sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR))
    print('wrote hitzones.json + %d bins, %.1f MB' % (len(blobs), tot / 1e6))


if __name__ == '__main__':
    main()
