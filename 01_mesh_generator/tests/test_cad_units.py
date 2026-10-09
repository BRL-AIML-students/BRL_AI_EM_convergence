from pathlib import Path

import gmsh
import numpy as np
import pytest
from pyNastran.bdf.bdf import BDF

from geometry_mesh.geometry import build
from geometry_mesh.pipeline import run


def write_brep(path, kind):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        if kind in {"box", "mixed"}:
            gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        if kind in {"sheet", "mixed"}:
            gmsh.model.occ.addRectangle(30, 0, 0, 1, 1)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


@pytest.mark.parametrize("kind,area,root_dims", [
    ("box", 600, [3]), ("sheet", 100, [2]), ("mixed", 700, [2, 3]),
])
def test_brep_roots_convert_once_and_nas_uses_output_units(tmp_path, kind, area, root_dims):
    source = tmp_path / "source.brep"
    write_brep(source, kind)
    report = run({"name": kind, "output_dir": str(tmp_path / "output"),
                  "length_unit": "cm", "output_unit": "mm",
                  "geometry": {"kind": "cad", "path": str(source)},
                  "mesh": {"controlled": True, "scale_fraction": .02}})
    assert report["status"] == "complete"
    assert [dim for dim, _ in report["geometry"]["root_entities"]] == root_dims
    assert report["geometry"]["surface_area"] == pytest.approx(area)
    expected_x = 10 if kind == "box" else 310
    assert report["geometry"]["bbox_max"][0] == pytest.approx(expected_x, abs=2e-5)
    nas = Path(report["output_directory"]) / report["artifacts"]["nas"]
    reader = BDF(debug=False)
    reader.read_bdf(str(nas), xref=False, punch=True)
    coordinates = np.asarray([node.xyz for node in reader.nodes.values()])
    assert coordinates[:, 0].max() == pytest.approx(expected_x)
    if kind == "mixed":
        sheet = coordinates[coordinates[:, 0] > 100]
        assert sheet[:, 0].min() == pytest.approx(300)
        assert sheet[:, 1].max() == pytest.approx(10)


def test_converted_brep_solid_can_be_used_in_csg(tmp_path):
    source = tmp_path / "box.brep"
    write_brep(source, "box")
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        geometry = build({"kind": "cut", "objects": [
            {"kind": "cad", "path": str(source)},
            {"kind": "box", "parameters": {"length": .5, "width": 1, "height": 1}},
        ]}, "cm", "mm")
        assert geometry["volume_count"] == 1
        assert gmsh.model.occ.getMass(3, geometry["root_entities"][0][1]) == pytest.approx(500)
    finally:
        gmsh.finalize()
