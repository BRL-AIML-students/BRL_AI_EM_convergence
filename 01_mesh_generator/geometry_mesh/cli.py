from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .pipeline import run_file


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Generate and validate a first-order triangular surface mesh.")
    result.add_argument("config", type=Path, help="version 1 JSON configuration")
    result.add_argument("--quiet", action="store_true", help="suppress progress messages")
    result.add_argument("--compare", action="store_true", help="generate baseline, waveOnly, autoSizeOnly and combined cases")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        progress = None if args.quiet else lambda text: print(text, file=sys.stderr)
        if args.compare:
            from .comparison import compare
            from .config import load
            report = compare(load(args.config), progress=progress)
        else:
            report = run_file(args.config, progress=progress)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "output_directory": report["output_directory"]}))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
