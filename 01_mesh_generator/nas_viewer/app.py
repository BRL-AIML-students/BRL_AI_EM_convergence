"""Open the dependency-free browser viewer, optionally with a NAS file preloaded."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import uuid
import webbrowser

from .nas import read


TEMPLATE = Path(__file__).resolve().parent.parent / "viewer.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the local NAS surface mesh viewer")
    parser.add_argument("nas", type=Path, nargs="?", help="free-field GRID/CTRIA3 NAS file to preload")
    args = parser.parse_args(argv)
    page = TEMPLATE
    if args.nas is not None:
        read(args.nas)  # Reject unsupported or malformed data before opening a browser.
        raw = args.nas.read_text(encoding="utf-8", errors="replace")
        html = TEMPLATE.read_text(encoding="utf-8")
        if "/*__NAS_DATA__*/" not in html:
            raise RuntimeError("viewer template marker is missing")
        payload = json.dumps(raw).replace("<", "\\u003c")
        html = html.replace("/*__NAS_DATA__*/", f"window.EMBEDDED_NAS = {payload}; window.EMBEDDED_NAME = {json.dumps(args.nas.name)};")
        directory = Path(tempfile.gettempdir()) / "brl_nas_viewer"
        directory.mkdir(exist_ok=True)
        page = directory / f"viewer_{uuid.uuid4().hex}.html"
        page.write_text(html, encoding="utf-8")
    if not webbrowser.open(page.resolve().as_uri()):
        print(f"Open this page in your browser: {page.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
