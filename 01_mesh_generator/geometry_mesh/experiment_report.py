"""Self-contained A/B report opened from the native ONELAB experiment actions."""
from pathlib import Path
import json


def write_comparison(path: Path, result: dict) -> None:
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("experiment_report.html").read_text(encoding="utf-8")
    path.write_text(template.replace("__COMPARISON_DATA__", payload), encoding="utf-8")
