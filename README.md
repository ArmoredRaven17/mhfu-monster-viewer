# MHFU Monster Viewer

A fan-made 3D viewer for the monsters of Monster Hunter Freedom Unite (PSP). Pick a monster and
watch its own animations, with the game's own models and textures.

**Basic version.** Forked from the MH4U Monster Viewer: monster rendering and animation, and the
MHGU viewers' Lighting, Camera, Effects and Hit Zones panels. The parts table (stagger and break
values) and sizes are not decoded yet.

## What it does

- 82 monsters: every species in the game's Monster List except the five it names "dummy" and two
  duplicates (see below).
- Each monster's **action entries** as clips, at the game's own speed (60 frames a second: a motion steps
  two frames per 30 Hz game update), with looping and frame stepping.
  The game stores no names for them, so they are numbered as the game numbers them.
- The game's own textures (TMH banks, 4- and 8-bit palettes), bound per material.
- **The tail tip is drawn in place.** A monster with a severable tail keeps the tip as a separate
  mesh on its own bone chain; while the tail is whole the game copies the tail joints' pose onto
  that chain every frame, so the build rebinds the tip to those joints.
- **Parts come from the game's own code.** Each monster's code decides, mesh by mesh, which materials
  it draws: at spawn, and as a part's flinch count, the tail cut, the broken-part flags, rage or a
  species state change. The build runs that code under emulation and the Parts panel has one control
  per state that changes the look. Every monster opens at spawn: intact and calm. The controls are
  unnamed ("Part 1", "Part 2" ...) until they are named by hand.
- Overlay meshes (Tigrex's rage layer, glowing eyes) follow the same rules, so they show when their
  state is switched on. Attack and movement effects are not shown yet.
- **Hit zones from the game's own tables**: each monster's damage table (cut, impact, shot, the five
  elements and stun) and its hit capsules, the spheres and capsules on the skeleton the game tests a hit
  against. The Hit Zones panel is the MHGU viewer's: a heat map per damage type, the chart, and a zone's
  capsules drawn on the moving monster. Monsters with more than one table (rage, broken parts and the like)
  list them under Damage Table; which state picks each one is not decoded yet, so they read "State 1",
  "State 2". Zones are "Slot N" until they are named by hand.

## Data pipeline

    python C:\MHFU-Extract\tools\iso.py          # BOOT.BIN + DATA.BIN out of the UMD image
    python C:\MHFU-Extract\tools\databin.py      # decrypt DATA.BIN -> C:\MHFU-Extract\data\fNNNN.bin
    python C:\MHFU-Extract\tools\convert.py      # monster PACs -> C:\MHFU-Extract\conv\monster\fNNNN
    python scripts/build_viewer.py               # conv -> docs/
    python C:\MHFU-Extract\tools\hitzones.py      # damage tables + capsules -> conv\monster\hitzones.json
    python scripts/build_hitzones.py             # -> docs/hitzones.json, docs/hitzones/*.bin

The script headers are the long reference; `C:\MHFU-Extract\CLAUDE.md` maps the files.

- A species `s` is DATA.BIN file `f(6111 + s)` on the US release, the number the game's Monster List
  counts in. The EU numbering is one lower.
- A monster PAC is: skeleton, PMO model, TMH textures, animation pack, and on some species a second
  small skeleton/model/textures (effects; not shown yet).
- Clips are baked from the game's keyframes (cubic Hermite, Euler rotations) into glTF quaternion
  tracks at 60 frames a second, then thinned with `scripts/reduce_keys.py`.

## Left out, and why

| Species | What it is |
|---|---|
| 10, 74 | "dummy": Felyne NPCs |
| 18 | "dummy": the Felyne cart that carries a fainted hunter |
| 29 | "dummy": a boulder |
| 32 | "dummy": a dressed pig |
| 72 | a second Yama Tsukami with a short move set |
| 89 | Golden Rajang: its file is byte-identical to Rajang's, so the gold is applied at run time |

## Credits

See [NOTICE.md](NOTICE.md). File formats after **MHFU-ModKit** (sp00ktober), **mhff** (Seth
VanHeulen) and **PMO-Importer** (AsteriskAmpersand); our converter is our own code.
