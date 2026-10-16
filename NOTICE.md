# Notices and attribution

## Game content

Monster Hunter Freedom Unite, and all of its models, textures, animations and data tables, are
© CAPCOM CO., LTD. All rights reserved.

This is an unofficial, non-commercial fan project. It is not affiliated with, endorsed by, or
supported by Capcom. All game assets were extracted from a personally owned copy of the game (the
US release, ULUS10391) and are shown for reference only.

## File-format references

The converter that reads the game's files (`C:\MHFU-Extract\tools`, see README.md) is this
project's own code. These projects' documentation and code were the format references it was
written from; none of their code is included here.

- **MHFU-ModKit** — sp00ktober. Format documentation for PAC containers, PMO models, TMH textures,
  skeletons and animation packs (`docs/formats`), and the way the severed tail tip pairs with the
  tail. https://github.com/MHFU-ModKit/modkit (MIT; its format library is GPL-3.0)
- **mhff** — Seth VanHeulen. Earlier PSP Monster Hunter file-format code that ModKit's PMO and TMH
  readers derive from. https://github.com/svanheulen/mhff (GPL-3.0)
- **PMO-Importer** — AsteriskAmpersand. Its PMO template (`PMO.bt`) was a second reference for the
  model format. https://github.com/AsteriskAmpersand/PMO-Importer (GPL-3.0)
- The DATA.BIN cipher and archive layout come from the same author's **MHFU LookUp** app's notes
  (`docs/rom-data-extraction.md`), found by disassembling the game's own `BOOT.BIN`.

## Tools used to build this

- **three.js** — rendering, `GLTFLoader`, `OrbitControls`, `SkeletonUtils`. https://threejs.org
- **Pillow**, **NumPy**, **pycdlib** — reading the disc image and the archive, texture conversion.

## Data

- Monster **names** are the game's own (the Monster List and the variant list in the English text).
  Where the game calls a variant by its base monster's name (the three Fatalis, the two Kushala
  Daora, the two Yian Garuga), or abbreviates it, the MHFU LookUp app's name is used.
- Monster **classes** and the **list order** are the MHFU LookUp app's (`monster_order.json`).
- Everything else — models, textures, skeletons, animations — is read out of the game's own files.
  What is not decoded yet (shading, the parts table, hit zones, sizes) is left out rather than
  approximated; `docs/monsters.json` `_about` says what is ROM-sourced.

## Assets

The monster and theme icons are the MHFU LookUp app's. The MHFU font and the UI textures are
shared with the sibling MHGU, MH3U and MH4U fan apps.

## Code

The viewer is a fork of the **MH4U Monster Viewer**, itself from the MH3U and MHGU Monster Viewers,
by the same author; its render modules are copies of those projects' files and are maintained here
independently.
