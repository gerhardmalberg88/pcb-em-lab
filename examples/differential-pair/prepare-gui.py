#!/usr/bin/env python3
"""Prepare writable inspection copies for this example's GUI tasks."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('board', 'circuit'))
    args = parser.parse_args()
    example = Path(__file__).resolve().parent
    results = example.parents[1] / 'results/examples/differential-pair'
    if args.kind == 'board':
        target = results / 'gui-source/board.kicad_pcb'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(example / 'board.kicad_pcb', target)
        print('Inspection copy:', target)
        print('The simulation still uses examples/differential-pair/board.kicad_pcb.')
    else:
        network = results / '3d/postprocess/network.s2p'
        if not network.is_file():
            parser.error('Run the 3D case through postprocess before opening its circuit.')
        target = results / 'gui-circuit/network.sch'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(example / 'network.sch', target)
        # Keep schematic edits, but refresh this generated network from the run.
        shutil.copy2(network, target.with_suffix('.s2p'))
        print('Inspection circuit:', target)


if __name__ == '__main__':
    main()
