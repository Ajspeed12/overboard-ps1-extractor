# Overboard! / Shipwreckers! — PS1 Extractor

Extract native resources, 20 campaign level environments, and a combined gallery of recovered assets from the **PlayStation 1** version of *Overboard!* (also released as *Shipwreckers!*).

Tested with the US PS1 release **SLUS_005.58**. PC game data is not supported. This tool extracts **static** assets, not a playable scene or reconstructed animation.

## Requirements

- Python 3.10+
- Pillow (`pip install -r requirements.txt`)
- Your own PS1 game files: `RES.RDR`, `RES.RDA`, `RES.RDT`

No Blender, NumPy or emulator is required for extraction.

## Quick start (Windows)

1. Place `RES.RDR`, `RES.RDA`, and `RES.RDT` in a folder named `game` beside the scripts.
2. Install dependencies: `py -3 -m pip install -r requirements.txt`.
3. Double-click `Build_All.bat`.
4. Find the resulting OBJ files in `Rebuilt_Collection`.

## Command line

```bash
python -m pip install -r requirements.txt
python unpack_resources.py game unpacked
python build_collection.py unpacked Rebuilt_Collection
```

Optional builds:

```bash
python build_collection.py unpacked Rebuilt_Collection --levels-only
python build_collection.py unpacked Rebuilt_Collection --assets-only
python build_collection.py unpacked Rebuilt_Collection --level 1 --levels-only
python build_collection.py unpacked Raw_Collection --raw-boundaries --levels-only
```

The unpacker writes an internal `archive_index.json` alongside its extracted BIN files. Keep this file when rebuilding from the unpacked directory.

## Outputs and Blender import

- `Rebuilt_Collection/Levels/`: five regions, four environment OBJs each (20 levels total)
- `Rebuilt_Collection/Assets/`: combined recovered asset gallery
- Keep OBJ files alongside their MTL files and associated texture folders.
- In Blender, enable **Split by Object** for the gallery. Typical import axes: **-Z forward, Y up**.
- Use Material Preview and **Closest** texture interpolation for the original pixelated appearance.

## Known limitations

- Static meshes and native bind/rest poses only; animation and gameplay spawn placements are not reconstructed.
- Eleven assembly records use component-only recovery. One shared shape has no matching native hierarchy, so its components are exported separately.
- Original PS1 blending, lighting, and runtime effects cannot be represented fully by OBJ/MTL. Blender may require manual alpha settings.
- Water and foam use frame 00; available texture-strip frames are retained.
- Native terrain boundaries are repaired selectively; `--raw-boundaries` retains original quantisation gaps.
- All 20 maps passed structural and OBJ/MTL/texture dependency checks in the original project validation, but not every level has been visually compared against gameplay.

## Legal

This repository contains extraction tools only. **No game files or extracted copyrighted assets are included.** You must supply your own game data. *Overboard!* and *Shipwreckers!* are trademarks of their respective owners.

## License

No open-source license has been selected yet. Add a `LICENSE` file once the intended permissions are decided.
