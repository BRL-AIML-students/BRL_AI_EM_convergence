from __future__ import annotations

import argparse
import json
import sys

from .config import Configuration
from .engine import run
from .errors import ConfigurationError, MeshBlocked


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='BRL 표면 메쉬 생성기 — 현재 단일 판만 지원')
    parser.add_argument('configuration', help='schema_version=1 JSON 설정 경로')
    args = parser.parse_args(argv)
    try:
        result = run(Configuration.load(args.configuration))
        print(json.dumps({'status': 'ok', 'nas_path': str(result.nas_path)}, ensure_ascii=False))
        return 0
    except (ConfigurationError, OSError) as exc:
        print(json.dumps({'status': 'error', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except MeshBlocked as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'status': 'error', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
