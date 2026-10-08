"""형상 치수와 최종 sizing 값을 사용하는 읽을 수 있는 결과 이름."""
from __future__ import annotations

from pathlib import Path
import re


def number(value: float) -> str:
    return format(float(value), ".12g").replace(".", "p").replace("-", "m").replace("+", "")


def source_name(cfg: dict) -> str:
    node = cfg["geometry"]
    original = cfg["naming"]["source_name"]
    if original is None:
        original = Path(node["path"]).name if node["kind"] == "cad" else node["kind"]
    original = str(original).replace("\\", "/").rsplit("/", 1)[-1]
    if Path(original).suffix.lower() in {".step", ".stp", ".iges", ".igs", ".brep"}:
        original = Path(original).stem
    cleaned = re.sub(r"[^\w.-]+", "_", original, flags=re.UNICODE).strip("._")
    return (cleaned or "geometry")[:48]


def resolve(cfg: dict, sizing: dict) -> str:
    if not cfg["naming"]["automatic"]:
        return cfg["name"]
    node = cfg["geometry"]
    labels = {"plate": (("length", "L"), ("width", "W")), "disk": (("radius", "R"),),
              "sphere": (("radius", "R"),), "box": (("length", "L"), ("width", "W"), ("height", "H")),
              "cylinder": (("radius", "R"), ("height", "H")), "ogive": (("D", "D"), ("L", "L"), ("t", "t"))}
    parts = [source_name(cfg)]
    if node["kind"] in labels:
        parts.extend(label + number(node["parameters"][key]) for key, label in labels[node["kind"]])
        parts.append(cfg["length_unit"])
    unit = cfg["output_unit"]
    parts.extend(("hMin" + number(sizing["minimum_size"]) + unit, "hMax" + number(sizing["target_size"]) + unit))
    wave = cfg["mesh"]["wave"]
    if wave["frequency_hz"] is not None:
        parts.extend(("f" + number(wave["frequency_hz"] / 1e9) + "GHz", "N" + number(wave["elements_per_wavelength"])))
    if cfg["naming"]["case"]:
        parts.append(cfg["naming"]["case"])
    return "_".join(parts)
