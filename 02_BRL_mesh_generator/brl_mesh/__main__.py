from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .config import Configuration
from .engine import run
from .errors import ConfigurationError, MeshBlocked

PROTOCOL = 'BRL_RESULT '


def execute(configuration: str) -> tuple[int, dict]:
    try:
        result = run(Configuration.load(configuration))
        return 0, {'status': 'ok', 'nas_path': str(result.nas_path)}
    except MeshBlocked as exc:
        return 2, {'status': 'blocked', 'reason': str(exc)}
    except Exception as exc:
        return 1, {'status': 'error', 'reason': str(exc)}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='BRL 표면 메쉬 생성기 — plate·STEP/IGES/BREP')
    parser.add_argument('configuration', help='schema_version=1 JSON 설정 경로')
    args = parser.parse_args(argv)
    # OCC emits native import notices even when General.Terminal is zero.
    # Capture the process pipes instead of manipulating DLL/native file handles.
    try:
        completed = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'brl_mesh.cli_worker',
                                    str(Path(args.configuration).resolve())],
                                   cwd=Path(__file__).resolve().parent.parent,
                                   capture_output=True, text=True, encoding='utf-8')
        payloads = [line[len(PROTOCOL):] for line in completed.stdout.splitlines() if line.startswith(PROTOCOL)]
        if len(payloads) != 1 or completed.returncode not in (0, 1, 2):
            raise RuntimeError(f'Gmsh 실행 프로세스가 완료 상태를 반환하지 않았습니다 (exit={completed.returncode})')
        state = json.loads(payloads[0])
        code = completed.returncode
        expected = 'ok' if code == 0 else ('error' if code == 1 else 'blocked')
        if (not isinstance(state, dict) or state.get('status') != expected or
                set(state) != {'status', 'nas_path' if code == 0 else 'reason'}):
            raise RuntimeError('실행 프로세스의 완료 상태가 유효하지 않습니다')
    except Exception as exc:
        code, state = 1, {'status': 'error', 'reason': str(exc)}
    print(json.dumps(state, ensure_ascii=False), file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
