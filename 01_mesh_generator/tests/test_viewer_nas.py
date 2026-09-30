from pathlib import Path

import pytest

from nas_viewer.nas import read


def test_reads_surface_and_preserves_pid(tmp_path: Path):
    source = tmp_path / "sample.nas"
    source.write_text(
        "$ length unit: mm\nGRID,10,,0.,0.,0.\nGRID,20,,1.,0.,0.\n"
        "GRID,30,,0.,1.,0.\nCTRIA3,7,42,10,20,30\nENDDATA\n",
        encoding="ascii",
    )
    mesh = read(source)
    assert mesh.triangles == [(0, 1, 2)]
    assert mesh.pids == [42]
    assert mesh.unit == "mm"


def test_rejects_missing_node(tmp_path: Path):
    source = tmp_path / "bad.nas"
    source.write_text(
        "GRID,1,,0.,0.,0.\nGRID,2,,1.,0.,0.\n"
        "CTRIA3,1,1,1,2,3\nENDDATA\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="missing nodes"):
        read(source)


def test_reads_gmsh_large_grid_and_small_triangle(tmp_path: Path):
    source = tmp_path / "gmsh.nas"
    source.write_text(
        "$ Created by Gmsh\n"
        "GRID*   1               0               0.00000000      0.00000000      \n"
        "*       0.00000000      \n"
        "GRID*   2               0               1.00000000      0.00000000      \n"
        "*       0.00000000      \n"
        "GRID*   3               0               0.00000000      1.00000000      \n"
        "*       0.00000000      \n"
        "CTRIA3  1       4       1       2       3       \nENDDATA\n",
        encoding="ascii",
    )
    mesh = read(source)
    assert mesh.node_ids == [1, 2, 3]
    assert mesh.triangles == [(0, 1, 2)]
    assert mesh.pids == [4]


def test_reads_small_fixed_fields_with_compact_exponent(tmp_path: Path):
    source = tmp_path / "small.nas"
    cards = [
        ["GRID", "1", "0", "0.0", "0.0", "0.0"],
        ["GRID", "2", "0", "1.0", "0.0", "0.0"],
        ["GRID", "3", "0", "0.0", "1.0-1", "0.0"],
        ["CTRIA3", "1", "2", "1", "2", "3"],
    ]
    source.write_text("\n".join("".join(f"{value:<8}" for value in card) for card in cards) + "\nENDDATA\n", encoding="ascii")
    mesh = read(source)
    assert mesh.coordinates[2] == (0.0, 0.1, 0.0)
    assert mesh.pids == [2]
