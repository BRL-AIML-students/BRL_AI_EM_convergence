from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from pyNastran.bdf.bdf import BDF


def write(path: Path, mesh: dict[str, Any], output_unit: str) -> None:
    lines = ["$ Geometry surface mesh; punch-style free-field data", f"$ length unit: {output_unit}"]
    for node_id, xyz in zip(mesh["node_ids"], mesh["coordinates"]):
        values = [_nas_float(value) for value in xyz]
        lines.append(f"GRID,{int(node_id)},,{values[0]},{values[1]},{values[2]}")
    for eid, pid, nodes in zip(mesh["element_ids"], mesh["pids"], mesh["connectivity"]):
        lines.append(f"CTRIA3,{int(eid)},{int(pid)},{int(nodes[0])},{int(nodes[1])},{int(nodes[2])}")
    lines.append("ENDDATA")
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def _nas_float(value: float) -> str:
    text = f"{float(value):.17g}"
    # pyNastran intentionally distinguishes integer lexical tokens in real fields.
    return text if any(marker in text for marker in ".eE") else text + ".0"


def validate(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[int, list[float]] = {}
    elements: dict[int, tuple[int, list[int]]] = {}
    cards: dict[str, int] = {}
    problems: list[int] = []
    try:
        for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("$"):
                continue
            fields = [field.strip() for field in line.split(",")]
            card = fields[0]
            cards[card] = cards.get(card, 0) + 1
            if card == "GRID" and len(fields) == 6:
                nodes[int(fields[1])] = [float(fields[3]), float(fields[4]), float(fields[5])]
            elif card == "CTRIA3" and len(fields) == 6:
                elements[int(fields[1])] = (int(fields[2]), list(map(int, fields[3:6])))
            elif card != "ENDDATA":
                return _failure(cards, f"unsupported or malformed card on line {line_number}: {card}")
    except (OSError, UnicodeError, ValueError) as exc:
        return _failure(cards, f"NAS parse failed: {exc}")
    if set(cards) != {"GRID", "CTRIA3", "ENDDATA"} or cards.get("ENDDATA") != 1:
        return _failure(cards, "card set must contain only GRID, CTRIA3, and one ENDDATA")
    expected_nodes = list(map(int, expected["node_ids"]))
    expected_elements = list(map(int, expected["element_ids"]))
    if sorted(nodes) != expected_nodes or sorted(elements) != expected_elements:
        return _failure(cards, "exported identifiers or counts differ from the mesh")
    exported_xyz = np.asarray([nodes[node] for node in expected_nodes])
    coordinate_error = float(np.max(np.abs(exported_xyz - expected["coordinates"])))
    for eid, expected_pid, expected_conn in zip(expected_elements, expected["pids"], expected["connectivity"]):
        pid, conn = elements[eid]
        if pid != int(expected_pid) or conn != list(map(int, expected_conn)):
            problems.append(eid)
    if problems:
        result = _failure(cards, "connectivity or PID changed during export")
        result["problem_element_ids"] = problems
        return result
    if not np.all(np.isfinite(exported_xyz)) or coordinate_error > 1e-12:
        return _failure(cards, f"coordinate round-trip error is {coordinate_error:.6g}")
    try:
        reader = BDF(debug=False)
        reader.read_bdf(str(path), xref=False, punch=True, encoding="ascii")
        unexpected = set(reader.card_count) - {"GRID", "CTRIA3", "ENDDATA"}
        if unexpected:
            return _failure(cards, f"independent reader found unsupported cards: {sorted(unexpected)}")
        if sorted(reader.nodes) != expected_nodes or sorted(reader.elements) != expected_elements:
            return _failure(cards, "independent reader found identifier/count mismatch")
        independent_xyz = np.asarray([reader.nodes[node].xyz for node in expected_nodes])
        for eid, expected_pid, expected_conn in zip(expected_elements, expected["pids"], expected["connectivity"]):
            element = reader.elements[eid]
            if element.type != "CTRIA3" or element.Pid() != int(expected_pid) or element.node_ids != list(map(int, expected_conn)):
                problems.append(eid)
        if problems or not np.allclose(independent_xyz, expected["coordinates"], rtol=0.0, atol=1e-12):
            result = _failure(cards, "independent reader found coordinate, connectivity, or PID mismatch")
            result["problem_element_ids"] = problems
            return result
    except Exception as exc:
        return _failure(cards, f"independent pyNastran validation failed: {exc}")
    return {
        "valid": True, "message": "validated", "card_counts": cards,
        "maximum_coordinate_roundtrip_error": coordinate_error,
        "identifiers_connectivity_and_pids_match": True,
        "independent_reader": "pyNastran",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "problem_element_ids": [],
    }


def _failure(cards: dict[str, int], message: str) -> dict[str, Any]:
    return {"valid": False, "message": message, "card_counts": cards, "problem_element_ids": []}
