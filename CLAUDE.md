# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A static single-page web app: every MHFU monster in 3D with its own animations. A **basic version**,
forked from the MH4U Monster Viewer (`C:\Coding Repos\mh4u-monster-viewer`).

No build step for the app, no framework. `docs/index.html` holds markup, styles and logic;
`docs/render/*.js` is the render core (ES modules, three.js 0.169 from jsdelivr). Serve `docs/` with
`dev/serve.py`.

## Data pipeline

The game files are read by `C:\MHFU-Extract\tools` (its CLAUDE.md maps DATA.BIN). This repo's
`scripts/build_viewer.py` turns the converter's output into `docs/`. Worth knowing:

- **The PSP files are converted into the 4U viewer's contract**, so the render core is unchanged:
  bones are nodes `"<i>:<i>"` with a `_s` leaf the skin binds to, `joints` per skin joint,
  materials keyed by glTF material name in `materials.json`. Units are metres (the game's are cm).
- **Blending is per mesh on the PSP, not per material**, so a glTF material is named `mKK` (opaque)
  or `mKK_<state>` (`blend`, `add`, `revsub`, `unlit-*`), one per state the PMO material draws in.
  Every alpha-blended mesh is an effect layer (`fx` in materials.json, picked up in
  render/monster.js) and starts hidden.
- **The tail tip is rebound in the converter** (`tip_chain`): the chain at `params[1]` mirrors the
  tail at one offset; the tip's vertices move by that offset onto the carrier joints. The dropped tail
  on the ground is not built; cutting the tail hides mesh 1 and shows the stump cap.
- **Parts are the game's own material pass, run under emulation** (`C:\MHFU-Extract\tools\vis_emu.py` ->
  `conv\monster\vis.json` -> build_viewer.py `part_controls` -> monsters.json `spawnHide` + `states`).
  Every monster opens at spawn (intact, calm). Each entity field that changes the look is one control,
  a flag word one control per bit. **Controls are unnamed on purpose** ("Part 1..n", options "Default",
  "Changed" / "State k"): Raven names them in `PART_LABELS` / `OPTION_LABELS`. The page applies them in
  `applyFuState` (index.html) by each mesh's `userData.fuKey` ("<mesh>/<material>", render/monster.js).
- Effect layers are no longer forced off: overlays (Tigrex's rage layer, glows) follow the game's rules
  (rage is a control). Attack/movement effects (the second model, action-driven materials) are not done.
- `SPAWN_SHOW` (build_viewer.py) is the one hand override: Vespoid Queen's wings, which the class's pass
  never draws (inferred look, see the comment).
- Clips are action entries: part k plays slot `e % 100` of stream `2k + e // 100`. A part with no
  clip in an entry borrows the first entry's (Tigrex 24/25 drive the head alone in game).
- **Every material alpha-tests at > 0**, as the game's model draw sets the GE (BOOT 0x08861C7C: ATST 0xDBFF0006
  around 0x0886171C). An opaque material whose map has alpha-0 texels ships `fb` + feat 1 (`Alpha`), the cutout
  render/material.js applies; without the feat it was drawn solid (black fur cards on 68 monsters).
- **Colours the game writes at spawn** (vis.json `spawnColour`, vis_emu.py): Cephadrome (its file is Cephalos'
  byte for byte, coloured 0x656041 by the class pass, game_task 0x09AE6670) and calm Emerald Congalala (0x7A9494).
  They ship as `cbm.diffuse` (linear, so the screen shows map x byte/255) with a neutral `glob`. Colours the pass
  copies from spawn-filled entity fields (`colourFromField`: Blangonga/Congalala families +0x7E7, Shen Gaoren,
  Monoblos) are not applied: the spawn code that fills them is not read yet.
- Motions are 60 fps: the game adds the motion's step (2.0, at entity+0x80 + 0x40k) to its frame once per
  30 Hz update (BOOT 0x088638C0). `convert.py` FPS and `FRAME` in index.html are both 60.
- Names: the game's two lists in f0019; `NAMES` in build_viewer.py overrides where the game repeats
  the base name. Classes and order are the MHFU LookUp app's `monster_order.json`, not ROM data.
- `SKIP` lists the dummies and duplicates left out; the README says what each is. Never put them on
  the page (leftover data belongs in notes).

- **Hit zones are read from MHFU's code** (`C:\MHFU-Extract\tools\hitzones.py`: the species record,
  damage tables, capsules and flag bits, every field with the address the game reads it at; `--check`
  runs the game's capsule routine over a save state). `scripts/build_hitzones.py` writes GU's
  hitzones.json contract with GU's bake, as the 4U viewer's builder does, so the panel is GU's.
  MHFU's own differences: nine columns (no exhaust), `capsuleFlags` are MHFU's bits (the masks ride in
  `_about`, read by `zoneNeverCounted` / `zoneSpecialOnly`), and tables after the first are
  "State k" (`TABLE_LABELS` for names) because which state sets entity+0x481 is not decoded. Zone and
  table names are Raven's to give.

The 4U page's parts-table and Apex code is still in index.html; MHFU's data leaves it idle
(`partTable` null, no part records, so the Extracts pane stays disabled). Comments marked "MH4U
(inherited, unused by MHFU's data)" are about that code.

## Conventions

- Storage keys are `mhfu-monster-viewer-*`.
- The theme palette is the MHFU Hunting Log's `COLORS` (the family's 31 hexes); keep it identical.
- Monster names come from the game's text; never put user text into the DOM with `innerHTML`.
- Credit every format reference in NOTICE.md, the README and the About dialog in the same change.
