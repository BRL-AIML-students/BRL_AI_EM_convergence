from pathlib import Path

import numpy as np

from geometry_mesh.nas import validate, write


def mesh():
    return {
        "node_ids": np.array([1, 2, 3]),
        "coordinates": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        "element_ids": np.array([10]), "connectivity": np.array([[1, 2, 3]]),
        "pids": np.array([7]), "surface_tags": np.array([1]),
    }


def test_nas_round_trip(tmp_path: Path):
    path = tmp_path / "one.nas"
    write(path, mesh(), "mm")
    result = validate(path, mesh())
    assert result["valid"]
    assert result["independent_reader"] == "pyNastran"
    assert "PSHELL" not in path.read_text()


def test_nas_rejects_extra_card(tmp_path: Path):
    path = tmp_path / "bad.nas"
    write(path, mesh(), "mm")
    path.write_text(path.read_text().replace("ENDDATA", "PSHELL,7,1,1.0\nENDDATA"))
    assert not validate(path, mesh())["valid"]

