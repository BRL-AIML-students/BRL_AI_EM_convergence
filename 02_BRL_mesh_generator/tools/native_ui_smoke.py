"""Developer smoke test: real FLTK window/event loop, API-injected Actions.

This verifies native lifecycle and shared-core publication, not widget layout or
mouse/keyboard interaction. Every run uses a new local output directory.
"""
from dataclasses import replace
import argparse
import json
from pathlib import Path
import uuid

import gmsh

from brl_mesh.config import Configuration
from brl_mesh import native_ui


def main():
    parser = argparse.ArgumentParser(description='실제 FLTK lifecycle 개발 검증')
    parser.add_argument('configuration', nargs='?', default='examples/plate.json')
    args = parser.parse_args()
    source = Path(args.configuration).resolve()
    output = Path('.cache/native-smoke').resolve() / uuid.uuid4().hex
    config = replace(Configuration.load(source), output_dir=output)
    original_wait, cycles = gmsh.fltk.wait, 0
    def pump(delay):
        nonlocal cycles
        original_wait(delay)
        cycles += 1
        if cycles == 2:
            gmsh.onelab.setString(native_ui.ACTION, [native_ui.ACTIONS[1]])
        elif cycles == 5:
            gmsh.onelab.setString(native_ui.ACTION, [native_ui.ACTIONS[5]])
    gmsh.fltk.wait = pump
    try:
        native_ui.launch(config, source.parent)
    finally:
        gmsh.fltk.wait = original_wait
    files = list(output.rglob('mesh.nas'))
    if len(files) != 1 or gmsh.isInitialized():
        raise RuntimeError('FLTK 발행/종료 검증에 실패했습니다')
    print(json.dumps({'fltk_cycles': cycles, 'nas_path': str(files[0]), 'session_finalized': True}))


if __name__ == '__main__':
    main()
