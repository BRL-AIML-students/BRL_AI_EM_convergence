from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re


@dataclass(frozen=True)
class Mesh:
    node_ids: list[int]
    coordinates: list[tuple[float, float, float]]
    element_ids: list[int]
    triangles: list[tuple[int, int, int]]  # zero-based coordinate indices
    pids: list[int]
    unit: str | None


def _real(token: str) -> float:
    # Nastran also permits 1.23-4 as a compact exponent.
    normalized = re.sub(r"(?<=\d)([+-]\d+)$", r"E\1", token.replace("D", "E").replace("d", "e"))
    value = float(normalized)
    if not math.isfinite(value):
        raise ValueError("coordinate must be finite")
    return value


def read(path: str | Path) -> Mesh:
    source = Path(path)
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: dict[int, tuple[int, tuple[int, int, int]]] = {}
    unit = None
    end_seen = False
    # Comments in third-party NAS files can use legacy encodings; the mesh cards
    # themselves are ASCII, so replacement characters in comments are harmless.
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line_number = i + 1
        i += 1
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$"):
            match = re.match(r"\$\s*length unit:\s*(\S+)", line, re.IGNORECASE)
            if match:
                unit = match.group(1)
            continue
        if end_seen:
            raise ValueError(f"line {line_number}: data after ENDDATA")
        if "," in line:
            fields = [field.strip() for field in line.split("$")[0].split(",")]
        else:
            card_name = raw[:8].strip().upper()
            if card_name == "GRID*":
                if i >= len(lines) or not lines[i][:8].strip().startswith("*"):
                    raise ValueError(f"line {line_number}: GRID* continuation is missing")
                continuation = lines[i]
                i += 1
                fields = ["GRID", raw[8:24].strip(), raw[24:40].strip(),
                          raw[40:56].strip(), raw[56:72].strip(), continuation[8:24].strip()]
            elif card_name in {"GRID", "CTRIA3"}:
                fields = [card_name] + [raw[start:start + 8].strip() for start in (8, 16, 24, 32, 40)]
            else:
                fields = [card_name]
        card = fields[0].upper()
        try:
            if card == "GRID":
                if len(fields) != 6:
                    raise ValueError("GRID needs 6 entries")
                nid = int(fields[1])
                if nid in nodes or nid <= 0:
                    raise ValueError("duplicate or invalid node ID")
                nodes[nid] = tuple(_real(value) for value in fields[3:6])
            elif card == "CTRIA3":
                if len(fields) != 6:
                    raise ValueError("CTRIA3 needs 6 entries")
                eid, pid = int(fields[1]), int(fields[2])
                triangle = tuple(int(value) for value in fields[3:6])
                if eid in elements or eid <= 0 or pid <= 0 or len(set(triangle)) != 3:
                    raise ValueError("duplicate or invalid triangle ID, PID, or vertices")
                elements[eid] = (pid, triangle)
            elif card == "ENDDATA":
                if len(fields) != 1:
                    raise ValueError("malformed ENDDATA")
                end_seen = True
            else:
                raise ValueError(f"unsupported card {card!r}")
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    if not end_seen or not nodes or not elements:
        raise ValueError("file needs GRID, CTRIA3, and ENDDATA cards")
    node_ids = sorted(nodes)
    index = {nid: i for i, nid in enumerate(node_ids)}
    element_ids = sorted(elements)
    triangles = []
    pids = []
    for eid in element_ids:
        pid, triangle = elements[eid]
        missing = set(triangle) - index.keys()
        if missing:
            raise ValueError(f"element {eid} references missing nodes: {sorted(missing)}")
        triangles.append(tuple(index[nid] for nid in triangle))
        pids.append(pid)
    return Mesh(node_ids, [nodes[nid] for nid in node_ids], element_ids, triangles, pids, unit)
