"""Usage: python unpack_resources.py GAME_DIRECTORY UNPACKED_DIRECTORY"""
import argparse
from overboard_native import unpack_archive

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Unpack PS1 RES.RDR / RES.RDA / RES.RDT resources.')
    p.add_argument('game_directory')
    p.add_argument('output_directory')
    a = p.parse_args()
    unpack_archive(a.game_directory, a.output_directory)
