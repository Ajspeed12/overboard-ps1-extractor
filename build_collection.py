"""Build the 20 campaign environments and one combined native asset gallery."""
import argparse
from pathlib import Path
from overboard_native import NativeArchive
from recover_assets import recover_assets


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('unpacked_directory')
    p.add_argument('output_directory')
    p.add_argument('--level', type=int, choices=range(1,21), help='Only this campaign environment (1-20).')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--levels-only', action='store_true')
    mode.add_argument('--assets-only', action='store_true')
    p.add_argument('--raw-boundaries', action='store_true', help='Retain source quantisation gaps for preservation comparisons.')
    a = p.parse_args()
    archive = NativeArchive(a.unpacked_directory)
    root = Path(a.output_directory)
    if not a.assets_only:
        for b, ref in archive.campaign_maps():
            if a.level is not None and b+1 != a.level:
                continue
            region, stage = b//4+1, b%4+1
            name = f'Region_{region:02d}_Level_{stage:02d}'
            archive.export_level(b, ref, root/'Levels'/f'Region_{region:02d}'/name, name, not a.raw_boundaries)
    if not a.levels_only:
        gallery, unresolved = recover_assets(archive, root/'Assets')
        if unresolved:
            print('One shared shape has no matching native hierarchy; its component meshes are exported separately.')
