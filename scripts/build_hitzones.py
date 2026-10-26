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
             hit code reads while entity+0x481 = k. Each class sets it in its own code; TABLE_NOTES gives the
             condition and the addresses for every table after the first (hitzones.py, TABLE STATES, has the
             decode), and the build stops if one is missing. Names are "State k" until Raven names them in
             TABLE_LABELS.
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
# What sets entity+0x481 to table k, by species then k: read from each class's code and replayed under
# C:\MHFU-Extract\tools\mips.py over save state 0 (C:\MHFU-Extract\tools\hitzones.py, TABLE STATES). A part's break
# count is entity+0x582 + 8*part, raised by 0x09AC7DFC each time the part's durability (+0x580 + 8*part) runs out;
# break flags are entity+0x774 (0x09AD7808 reads one); actions are (+0x298, +0x299); rage is +0x638 & 0x20.
_GRAVIOS = ('Once part 6\'s break count reaches %d: the part-break table at 0x09BCE9E0 (entry %d) sets it at '
            '0x09AD4BEC, run by 0x09AC7A08 when a count rises. Nothing sets it back.')
_TIGREX = ('While enraged (entity+0x638 & 0x20): the class update (em75, vtable slot 29) writes it every frame at '
           '0x09D35688 / 0x09D35690.')
_HORN = ('Once break flag 2 (entity+0x774 bit 2) is set: the class update (em75, vtable slot 29) writes it every frame '
         'at %s. The class\'s part routine (vtable slot 56) raises the flag at %s when part %d\'s break count is 2 or '
         'more and part %d takes a hit with hit bit %s (entity+0x3B0 + part, %s); it is not cleared after spawn.')
_AURA = ('While the class\'s aura test passes (em54, vtable slot %d at %s): entity+0x7D2 non-zero, break flags 0 '
         'and 2 clear, +0x4C4 and +0x454 at 0, +0x3CF not 4, not in action (4,12). The update (slot 29) then writes '
         '1 and sets +0x635 = 2, the gate of the "only while entity+0x635" capsules (0x09D2B498 / 0x09D2B4CC), '
         'else 0 (0x09D2B460..0x09D2B470), every frame.')
_DAIMYO = ('In actions (3,4) and (3,25) (dispatched by 0x09B26610 and 0x09B24278), 0x09B22598 sets +0x634 = 10 and '
           'writes %s every frame. Each action change sets it back to 0 (vtable slot 32, 0x09B26754).')
_CONGA = ('From frame 40 of clip 0x51 to that clip\'s end, in actions (3,10), (3,30), (3,31) and (4,18) (dispatched '
          'by 0x09B417E0): set as frame 40 passes (0x09B3940C, 0x09B3A7FC, 0x09B3D114), cleared when the clip ends '
          'and the action moves to clip 0x52 (0x09B39448, 0x09B3A868, 0x09B3D150) or the action changes (vtable '
          'slot 32, 0x09B30E30). Actions (3,30) and (3,31) also set +0x635 = 2 from frame 40 (0x09B3A820).')
TABLE_NOTES = {
    17: {1: _GRAVIOS % (2, 7)},                     # Gravios
    47: {1: _GRAVIOS % (2, 7)},                     # Black Gravios: the table's species group is Gravios's
    22: {1: _GRAVIOS % (1, 8)},                     # Basarios
    75: {1: _TIGREX},                               # Tigrex
    81: {1: _TIGREX},                               # Nargacuga
    76: {1: _HORN % ('0x09D35638 / 0x09D35640', '0x09D3F570', 1, 1, '0x01',
                     'set at 0x09C44BE4 from the hit routine\'s flag at sp+0x88, raised for attacks with +0x25 '
                     'bit 0 at 0x09C43A94 and dropped at 0x09C43CC0')},                     # Akantor
    88: {1: _HORN % ('0x09D35658 / 0x09D3565C', '0x09D3F628', 2, 2, '0x04',
                     'set at 0x09C44C6C for attacks with +0x28 bit 4')},                   # Ukanlos
    54: {1: _AURA % (20, '0x09D1F4E8')},            # Kushala Daora
    60: {1: _AURA % (20, '0x09D1F4E8')},            # Rusted Kushala Daora
    64: {1: _AURA % (21, '0x09D1F5A8')},            # Lunastra (slot 21 is the same code as 20)
    65: {1: _AURA % (21, '0x09D1F5A8')},            # Teostra
    59: {1: 'While it cloaks: the update (em59, vtable slot 29) writes slot 23 (0x09D1D9C0) == 1 at 0x09D25234 / '
            '0x09D25238 every frame, and the same answer sets its opacity target +0x798 to 0, else 0xFF. Slot 23 is '
            '1 while the fade counter +0x7EC runs (not 0xFFFF), or else when 0x09D1DBB0 passes: 0x09AD4360 finds '
            'nothing, then actions (2,0x19)..(2,0x1D) pass; otherwise +0x794 set, not in action group 5 or actions '
            '(6,1), (6,2), (1,4), +0x3CF not 2 or 4, not tail cut (+0x2B8 bit 0) with break flag 0, and action id '
            '+0x324 outside 0x411..0x41D or one of 0x414, 0x418, 0x41D. Its rage test (0x09D1DD24) cannot change '
            'the answer.'},                         # Chameleos
    36: {1: 'While enraged (entity+0x638 & 0x20): the class update (em02, vtable slot 29) writes it every frame at '
            '0x09D1A5C4 / 0x09D1A5D0, and leaves it as it was while +0x298 is 5.'},           # Crimson Fatalis
    71: {1: 'While HP (+0x2E4) is above trunc(0.2 x max HP +0x41E) and at most trunc(0.5 x max HP): the class '
            'update (em02, vtable slot 29) writes it every frame at 0x09D1A6A8..0x09D1A6D0.'},  # White Fatalis
    48: {1: _DAIMYO % '1 while part 5 or part 6 has a break count under 2 (0x09B22610)',
         2: _DAIMYO % '2 once parts 5 and 6 both have a break count of 2 or more (0x09B22608)'},  # Daimyo
    86: {1: _DAIMYO % '1 while part 5 or part 6 has a break count under 2 (0x09B22610)',
         2: _DAIMYO % '2 once parts 5 and 6 both have a break count of 2 or more (0x09B22608)'},  # Plum Daimyo
    67: {1: 'Once part 2\'s break count is 2 or more: the class update (vtable slot 29) writes it every frame at '
            '0x09B1F274; the clear at each action change (slot 32, 0x09B26754) is rewritten by the next update.'},
    87: {1: 'Once part 2\'s break count is 2 or more: the class update (vtable slot 29) writes it every frame at '
            '0x09B1F274; the clear at each action change (slot 32, 0x09B26754) is rewritten by the next update.'},
    52: {1: _CONGA},                                # Congalala
    85: {1: _CONGA},                                # Emerald Congalala
}


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
        missing = [k for k in range(1, n) if k not in TABLE_NOTES.get(s, {})]
        if missing:
            sys.exit('%s (species %d): no TABLE_NOTES for table %s' % (e['id'], s, missing))
        rec.update({
            'bin': 'hitzones/%s.bin' % e['id'],
            'tables': [[dict(zip(cols, row)) for row in t] for t in d['tables']],
            'tableNames': ['Default'] + [TABLE_LABELS.get((s, k), 'State %d' % k) for k in range(1, n)],
            'tableNotes': [''] + ['The table the hit code reads while entity+0x481 = %d. %s' % (k, TABLE_NOTES[s][k])
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
