r"""Build the MHFU Monster Viewer's data from the converted game files.

    python C:\MHFU-Extract\tools\convert.py     # monster PACs -> C:\MHFU-Extract\conv\monster\fNNNN
    python scripts/build_viewer.py              # conv -> docs/
    python scripts/build_viewer.py --only 75,81 # a subset (monsters.json is rewritten from them)

Reads  C:\MHFU-Extract\conv\monster\fNNNN\  model.glb, anim.glb, tex/NN.png, manifest.json
       C:\MHFU-Extract\data\f0019.bin        the game's English text (monster names)
       C:\Coding Repos\MHFU App\web\public\  monster_order.json (class + order) and the monster icons
Writes docs/:
  models/monsters/emNNN.glb   the model with its textures taken out (they ship once, as WebP)
  poses/monsters/emNNN.glb    the skeleton nodes + one animation per action entry, keys thinned
  tex/<md5[:16]>.webp         each unique texture once, lossless
  assets/MonsterIcons/*.png   the MHFU LookUp app's monster icons
  monsters.json, materials.json   the MH4U Monster Viewer's data contract, MHFU-sourced

A species s is DATA.BIN file f(6111 + s) on the US release (ULUS10391), the number the game's own
Monster List counts in. What is ROM-sourced and what is not is written into monsters.json's `_about`.
"""
import argparse, datetime, hashlib, io, json, os, re, shutil, struct, sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import reduce_keys
from glbtools import glb_read, glb_write, bone_nodes

EXTRACT = r'C:\MHFU-Extract'
CONV = os.path.join(EXTRACT, 'conv', 'monster')
LOOKUP = r'C:\Coding Repos\MHFU App\web\public'
DOCS = os.path.join(REPO, 'docs')
FIRST_FILE = 6111                    # species s -> f(FIRST_FILE + s)

# Species the game's Monster List names "dummy", and the two that duplicate another. Kept out of the
# viewer; what each is goes in the README's decode notes, not on the page.
SKIP = {
    10: 'dummy: a Felyne NPC with a pack',
    18: 'dummy: the Felyne cart that carries a fainted hunter',
    29: 'dummy: a boulder',
    32: 'dummy: a dressed pig',
    74: 'dummy: a Felyne NPC in a mining helmet',
    72: 'a second Yama Tsukami with a short move set; the Monster List names it but the variant list does not',
    89: 'byte-identical to Rajang (53): Golden Rajang\'s colour is applied at run time',
}
# Where the game's variant list repeats the base monster's name or abbreviates, the MHFU LookUp app's
# name (the family's spelling). Picked by model: 2 black, 36 red, 71 white; 60 brown; 78 has its own model.
NAMES = {
    2: 'Fatalis', 36: 'Crimson Fatalis', 71: 'White Fatalis', 60: 'Rusted Kushala Daora',
    78: 'Yian Garuga (One Eyed)', 50: 'Ashen Lao-Shan Lung', 86: 'Plum Daimyo Hermitaur',
    87: 'Terra Shogun Ceanataur',
}
# The small monsters, by species: the page's Small section, everything else is Large. Not read from the
# game (its large / small flag isn't decoded for MHFU); the same set as the MHFU Hunting Log's SMALL
# (scripts/build_data.py there), so the two apps agree. The bosses of a small kind -- King Shakalaka (79),
# Vespoid Queen (80), Bulldrome (68), the -dromes, Daimyo and Shogun -- are Large.
SMALL = {
    9: 'Felyne', 23: 'Melynx', 57: 'Shakalaka', 19: 'Vespoid', 24: 'Hornetaur', 56: 'Great Thunderbug',
    69: 'Anteka', 70: 'Popo', 3: 'Kelbi', 4: 'Mosswine', 12: 'Aptonoth', 25: 'Apceros',
    35: 'Giaprey', 16: 'Velociprey', 13: 'Genprey', 30: 'Ioprey', 63: 'Remobra', 34: 'Cephalos',
    62: 'Conga', 61: 'Blango', 5: 'Bullfango', 66: 'Hermitaur', 73: 'Ceanataur',
}
CLASS_ORDER = ['Lynian', 'Neopteron', 'Herbivore', 'Bird Wyvern', 'Flying Wyvern', 'Piscine Wyvern',
               'Carapaceon', 'Pelagus', 'Elder Dragon']
STATE = ['opaque', 'blend', 'add', 'revsub']
FEAT = [{'transp': 'AlphaConstant'},          # render/material.js: blend by the texture's alpha
        {'transp': 'Alpha'}]                  # cut out where the texture's alpha is 0 (the GE alpha test)
FEAT_CUTOUT = 1
# glob record 0: changes nothing by itself (albedo 1, no emission, no specular, clip 0), so a material that takes
# it for its cbm colour is drawn as before but for that colour
GLOB_NEUTRAL = {'albedo': [1.0, 1.0, 1.0, 1.0], 'emission': [0.0, 0.0, 0.0], 'shininess': 0, 'clip': 0,
                'fresnel': 1.0, 'fresnelSchlickRGB': [1.0, 1.0, 1.0], 'constant': [1.0, 1.0, 1.0, 1.0]}


# PART CONTROLS. The game decides what a monster draws in its own code (slot 25 of the species vtable, run
# under emulation by C:\MHFU-Extract\tools\vis_emu.py into conv\monster\vis.json): at spawn, and as entity
# fields change -- a part's flinch count (0x582 + 8k), the tail cut (0x2B8, 0x579), the broken-part bits
# (0x774), the state flags (0x638: rage), species fields (0x7xx). Each field that changes the look becomes a
# control; a bit field becomes one control per bit. Controls are named "Part 1..n" until Raven names them
# here: PART_LABELS[(species, control id)] = 'name'. Option names likewise (OPTION_LABELS).
PART_LABELS = {}
OPTION_LABELS = {}
# Groups drawn at spawn although the material pass hides them. Vespoid Queen (80): the Vespoid class's pass
# (game_task 0xB5758) zeroes her wing materials (slots 1, 5, 6, 7) outright, so the game must draw her wings
# some other way, not found yet. Shown as the Vespoid and Hornetaur draw theirs at rest (slots 1 and 5):
# inferred, not read.
SPAWN_SHOW = {80: ['0/1', '0/5']}
SEVER_FIELDS = {0x2B8, 0x579}       # the tail cut: the engine also stops drawing mesh 1, the tip (TAIL_DROP)
BIT_FIELDS = {0x638, 0x774}         # flag words: one control per bit


def part_controls(species, vis, tip):
    """vis.json's entry for one species -> (spawn-hidden groups, controls)."""
    spawn_hide = sorted(k for k, a in vis.get('spawn', {}).items() if a == 0 and k not in SPAWN_SHOW.get(species, []))
    controls = []
    for st in vis.get('states', []):
        field, size = int(st['field'], 16), st['size']
        # one option per distinct (show, hide) change; alpha fades of the same groups are one option
        opts = {}
        for o in st['outcomes']:
            key = (tuple(o['show']), tuple(o['hide']))
            opts.setdefault(key, []).extend(o['values'])
        if field in BIT_FIELDS or size > 1:
            groups = []
            for (show, hide), vals in opts.items():
                bits = [v for v in vals if v & (v - 1) == 0]
                groups.append((min(bits or vals), show, hide))
            for bit, show, hide in sorted(groups):
                controls.append({'field': field, 'value': bit, 'options': [{'show': list(show), 'hide': list(hide)}]})
        else:
            stages = sorted(((min(vals), show, hide) for (show, hide), vals in opts.items()))
            controls.append({'field': field, 'value': None,
                             'options': [{'value': v, 'show': list(show), 'hide': list(hide)} for v, show, hide in stages]})
    out = []
    for n, c in enumerate(controls, 1):
        cid = f"{c['field']:x}" + (f":{c['value']:x}" if c['value'] is not None else '')
        options = [{'label': OPTION_LABELS.get((species, cid, 0), 'Default'), 'show': [], 'hide': []}]
        for k, o in enumerate(c['options'], 1):
            options.append({'label': OPTION_LABELS.get((species, cid, k), f'State {k}' if len(c['options']) > 1 else 'Changed'),
                            'show': o['show'], 'hide': o['hide'],
                            'hideMeshes': [1] if c['field'] in SEVER_FIELDS and tip else []})
        out.append({'id': cid, 'label': PART_LABELS.get((species, cid), f'Part {n}'),
                    'field': f"0x{c['field']:x}" + (f" bit {c['value'].bit_length() - 1}" if c['value'] is not None else ''),
                    'options': options})
    return spawn_hide, out


def game_names():
    """The two monster name lists in the English text (f0019): the Monster List, one name per species
    (0 = "NO DATA", variants under their base name), then a list without the five dummies' gaps that
    names the variants. Returns {species: name}."""
    d = open(os.path.join(EXTRACT, 'data', 'f0019.bin'), 'rb').read()
    i = d.index(b'NO DATA\0Rathian\0')
    first = d[i:i + 4000].split(b'\0')
    n = first.index(b'NO DATA', 1)
    first = [x.decode('latin1') for x in first[:n]]
    j = d.index(b'NO DATA\0Rathian\0', i + 1)
    second = [x.decode('latin1') for x in d[j:j + 4000].split(b'\0')]
    # the second list drops entries; align it on the first by base name
    out, k = {}, 0
    for s, base in enumerate(first):
        if k < len(second) and (second[k] == base or base in second[k] or second[k].endswith(base.split()[-1])):
            out[s] = second[k]
            k += 1
        else:
            out[s] = base
    return out


def slug(name):
    s = name.lower().replace("'", '').replace('(', '').replace(')', '')
    return re.sub(r'[^a-z0-9-]+', '_', s).strip('_').replace('yian_kut-ku', 'yian_kut_ku')


def webp(png_path):
    im = Image.open(png_path).convert('RGBA')
    buf = io.BytesIO()
    im.save(buf, 'WEBP', lossless=True, quality=100, method=6)
    return buf.getvalue(), im


def strip_textures(js):
    for m in js.get('materials', []):
        m.get('pbrMetallicRoughness', {}).pop('baseColorTexture', None)
    for k in ('images', 'textures', 'samplers'):
        js.pop(k, None)


def compact(js, bin_):
    """Drop bufferViews nothing references (the embedded PNGs) and repack the buffer."""
    used = {a['bufferView'] for a in js['accessors']}
    order = sorted(used)
    remap, out = {}, bytearray()
    views = []
    for old in order:
        bv = js['bufferViews'][old]
        while len(out) % 4:
            out.append(0)
        start = len(out)
        out += bin_[bv.get('byteOffset', 0): bv.get('byteOffset', 0) + bv['byteLength']]
        nb = dict(bv, byteOffset=start)
        remap[old] = len(views)
        views.append(nb)
    for a in js['accessors']:
        a['bufferView'] = remap[a['bufferView']]
    js['bufferViews'] = views
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated species numbers')
    ap.add_argument('--skip-poses', action='store_true', help='keep the shipped pose glbs (their thinning is the slow part)')
    args = ap.parse_args()
    only = {int(x) for x in args.only.split(',')} if args.only else None

    names = game_names()
    vis_all = json.load(open(os.path.join(CONV, 'vis.json')))
    order = json.load(open(os.path.join(LOOKUP, 'data', 'monster_order.json')))
    klass, rank = {}, {}
    for c, slugs in order.items():
        for k, sl in enumerate(slugs):
            klass[sl], rank[sl] = c, k
    for sub in ('models/monsters', 'poses/monsters', 'tex', 'assets/MonsterIcons'):
        os.makedirs(os.path.join(DOCS, sub), exist_ok=True)

    monsters, mats_db, glb_map, notes = [], {}, {}, []
    cbm = []                                      # materials.json cbm: one record per game-written colour

    def cbm_index(hexrgb):
        # The GE multiplies in display space; three.js multiplies a linear colour into a linear map and then
        # encodes to sRGB. So the byte goes in as its linear value, and the screen shows the map x byte/255.
        def lin(b):
            c = b / 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        rgb = [round(lin(int(hexrgb[i:i + 2], 16)), 5) for i in (0, 2, 4)]
        rec = {'diffuse': rgb + [1.0], 'transparency': 1.0, 'reflective': [1.0, 1.0, 1.0]}
        if rec not in cbm:
            cbm.append(rec)
        return cbm.index(rec)
    for folder in sorted(os.listdir(CONV)):
        if not re.fullmatch(r'f\d{4}', folder):
            continue
        fid = int(folder[1:])
        s = fid - FIRST_FILE
        if s in SKIP or (only and s not in only):
            continue
        man = json.load(open(os.path.join(CONV, folder, 'manifest.json')))
        name = NAMES.get(s, names[s])
        sl = slug(name)
        if sl not in klass:
            sys.exit(f'species {s} {name!r}: no class in monster_order.json ({sl})')
        em = f'em{s:03d}'
        model = man['model']

        # textures -> WebP pool
        tex_paths = []
        for i in range(len(model['textures'])):
            data, im = webp(os.path.join(CONV, folder, 'tex', f'{i:02d}.png'))
            h = hashlib.md5(data).hexdigest()[:16]
            rel = f'tex/{h}.webp'
            path = os.path.join(DOCS, rel)
            if not os.path.exists(path):
                open(path, 'wb').write(data)
            tex_paths.append(rel)

        # model glb, textures out; materials.json binds them
        js, bin_ = glb_read(os.path.join(CONV, folder, 'model.glb'))
        strip_textures(js)
        bin_ = compact(js, bin_)
        glb_rel = f'models/monsters/{em}.glb'
        glb_write(os.path.join(DOCS, glb_rel), js, bin_)
        ref = f'em/{s:03d}'
        glb_map[glb_rel] = ref
        # THE MATERIAL COLOUR THE GAME WRITES at spawn (vis.json spawnColour, C:\MHFU-Extract\tools\vis_emu.py):
        # Cephadrome shares Cephalos' file byte for byte and is coloured 0x65 0x60 0x41 by the class's pass. The
        # GE takes it as the material colour; here it multiplies the map (cbm.diffuse x a neutral glob.albedo,
        # render/material.js). Per PMO material, so every draw state of it takes the same colour.
        tints = {}
        for key, hexrgb in vis_all.get(str(s), {}).get('spawnColour', {}).items():
            mk = int(key.split('/')[1])
            assert tints.get(mk, hexrgb) == hexrgb, (s, key, 'one material, two colours')
            tints[mk] = hexrgb
        mats = {}
        for gm in js.get('materials', []):
            nm = gm['name']
            k = int(nm[1:3])
            state = nm[4:] if len(nm) > 3 else 'opaque'
            unlit = state.startswith('unlit')
            blend = state.replace('unlit-', '').replace('unlit', 'opaque') or 'opaque'
            rec = {'s': STATE.index(blend)}
            t = model['materials'][k]['tex']
            if t is not None and t < len(tex_paths):
                rec['t'] = {'albedo': t + 1}
                if blend == 'opaque':
                    # THE ALPHA TEST. The model draw (BOOT 0x08861C7C / 0x08861D7C) sets the GE alpha test to
                    # GREATER 0 (ATST 0xDBFF0006) around every model it draws (0x0886171C) and puts the
                    # default GEQUAL 0x80 back after, so the game discards a texel of alpha 0 on every
                    # material, opaque meshes included (wing membranes, manes, fur cards). An opaque
                    # material whose map has such texels takes the cutout: fb's alpha-test bit plus the
                    # 'Alpha' feature, which is what render/material.js cuts on (alpha < ALPHA_EPS).
                    im = Image.open(os.path.join(CONV, folder, 'tex', f'{t:02d}.png'))
                    if im.mode == 'RGBA' and im.getextrema()[3][0] == 0:
                        rec['fb'] = '00100000'
                        rec['f'] = FEAT_CUTOUT
            if blend != 'opaque':
                rec['f'] = 0
            if unlit:
                rec['cls'] = 'Unlit'
            if k in tints:
                rec['g'] = 0
                rec['c'] = cbm_index(tints[k])
            mats[nm] = rec
        mats_db[ref] = {'tex': tex_paths, 'mats': mats}

        # animations: thinned copy
        pose_rel = f'poses/monsters/{em}.glb'
        if not (args.skip_poses and os.path.exists(os.path.join(DOCS, pose_rel))):
            shutil.copyfile(os.path.join(CONV, folder, 'anim.glb'), os.path.join(DOCS, pose_rel))
            reduce_keys.fix(os.path.join(DOCS, pose_rel))

        icon_src = os.path.join(LOOKUP, 'assets', 'Monsters', sl + '.png')
        icon = None
        if os.path.exists(icon_src):
            icon = f'assets/MonsterIcons/{sl}.png'
            shutil.copyfile(icon_src, os.path.join(DOCS, icon))
        else:
            notes.append(f'{em} {name}: no icon {sl}.png')

        tris = sum(m['tris'] for m in model['meshes'])
        controls = part_controls(s, vis_all.get(str(s), {}), model.get('tip'))
        monsters.append({
            'id': em, 'em': em, 'file': fid, 'small': s in SMALL,
            'name': name, 'nameRom': names[s], 'icon': icon, 'model': em, 'sharesModelOf': None,
            'sizeBase': 1.0, 'groups': None, 'partTable': None, 'partCode': None, 'parts': [],
            'lists': [{'id': em + ':0', 'stem': em, 'file': pose_rel, 'shared': False, 'label': 'Actions',
                       'clips': [{'clip': c['clip'], 'dur': c['dur']} for c in man['clips']]}],
            'glb': glb_rel, 'joints': model['joints'], 'boneNodes': bone_nodes(js),
            'hide': [], 'hideIdx': [], 'prims': sum(len(m['materials']) for m in model['meshes']),
            'bones': len(model['bones']), 'verts': sum(js['accessors'][pr['attributes']['POSITION']]['count'] for me in js.get('meshes', []) for pr in me['primitives']), 'tris': tris, 'meshes': len(model['meshes']),
            'skinned': True, 'species': klass[sl], 'speciesIdx': CLASS_ORDER.index(klass[sl]),
            'speciesFrom': 'MHFU LookUp app', 'listRank': rank[sl], 'eyesClosedParts': [],
            'partUi': None, 'inGU': False, 'tip': model.get('tip'),
            'spawnHide': controls[0], 'states': controls[1],
        })
        print(f'{em} {name:24s} {klass[sl]:15s} {len(man["clips"]):3d} clips  {tris:5d} tris')

    shutil.copyfile(os.path.join(LOOKUP, 'assets', 'Monsters', '_unknown.png'),
                    os.path.join(DOCS, 'assets', 'MonsterIcons', '_unknown.png'))   # the "?" fallback
    monsters.sort(key=lambda e: (e['speciesIdx'], e['listRank']))
    about = {
        'rom': 'Models, textures, skeletons, animations and names are read from the US game (ULUS10391) '
               'by C:\\MHFU-Extract\\tools (DATA.BIN decrypted with the MHFU LookUp app\'s cipher notes; '
               'PAC/PMO/TMH/animation layouts after MHFU-ModKit\'s docs).',
        'not_rom': 'Monster classes and list order are the MHFU LookUp app\'s (monster_order.json); '
                   'the names of variants the game calls by their base name are the LookUp app\'s too. '
                   'Clips are the game\'s action entries, at 60 frames a second (a motion steps 2 frames per 30 Hz update).',
    }
    now = datetime.datetime.now().isoformat(timespec='seconds')
    json.dump({'version': 1, 'generated': now, '_about': about, 'monsters': monsters},
              open(os.path.join(DOCS, 'monsters.json'), 'w'), indent=1)
    json.dump({'_about': 'Per model glb: its textures and, per glTF material name, the albedo (1-based into '
                         'tex), the draw state (index into state), f (feat), fb (alpha-test bit), cls '
                         '(Unlit for meshes drawn without lighting), g/c (glob/cbm: the material colour the '
                         'game writes at spawn, cbm.diffuse; glob is neutral).',
               'state': [{'blend': b} for b in STATE], 'feat': FEAT, 'glob': [GLOB_NEUTRAL], 'cbm': cbm,
               'glb': glb_map, 'monsters': mats_db},
              open(os.path.join(DOCS, 'materials.json'), 'w'), indent=1)
    print(f'{len(monsters)} monsters')
    for n in notes:
        print('NOTE', n)


if __name__ == '__main__':
    main()
