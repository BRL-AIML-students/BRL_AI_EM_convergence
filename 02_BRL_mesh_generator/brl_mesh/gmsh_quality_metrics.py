"""Independent Gmsh quality measurements; no scoring."""
from __future__ import annotations

import gmsh
import numpy as np

from .triangle_shape_checks import measure_shape
from .mesh_generator_errors import MeshBlocked
from .surface_mesh_snapshot import SurfaceMesh, assert_current


def read_radius_ratio(mesh: SurfaceMesh) -> np.ndarray:
    """Return normalized Gmsh gamma (2r/R) in first-order triangle ID order."""
    assert_current(mesh)
    values = np.asarray(gmsh.model.mesh.getElementQualities(mesh.element_ids, 'gamma'))
    if (values.shape != mesh.element_ids.shape or not np.isfinite(values).all() or
            np.any(values <= 0) or np.any(values > 1 + 1e-12)):
        raise MeshBlocked('Gmsh gamma 값이 누락됐거나 1차 삼각형 radius ratio 범위를 벗어났습니다')
    return values


def add_quality_view(mesh: SurfaceMesh, metric: str) -> int:
    """Create one Gmsh ElementData view for a current surface mesh."""
    if metric == 'ICN':
        icn = read_icn(mesh)
        values = np.array([icn[int(tag)] for tag in mesh.element_ids])
        if np.any(values <= 0):
            raise MeshBlocked('Plugin ICN이 양의 유효 값을 반환하지 않았습니다')
    elif metric == 'IGE':
        ige = read_ige(mesh)
        values = np.array([ige[int(tag)] for tag in mesh.element_ids])
    elif metric == 'Aspect ratio':
        assert_current(mesh)
        values = measure_shape(mesh).aspect_ratios
    elif metric == 'Radius ratio':
        values = read_radius_ratio(mesh)
    else:
        raise ValueError(f'지원하지 않는 품질 표시입니다: {metric}')
    is_ar = metric == 'Aspect ratio'
    tag = gmsh.view.add(f'BRL {metric}')
    try:
        gmsh.view.addHomogeneousModelData(tag, 0, gmsh.model.getCurrent(), 'ElementData',
                                          mesh.element_ids, values, numComponents=1)
        for name, value in {'RangeType': 2, 'CustomMin': 1 if is_ar else 0,
                            'CustomMax': max(3., float(values.max())) if is_ar else 1,
                            'SaturateValues': 1, 'ColormapNumber': 23,
                            'ColormapInvert': int(is_ar), 'ShowScale': 1, 'Visible': 1}.items():
            gmsh.view.option.setNumber(tag, name, value)
    except Exception:
        gmsh.view.remove(tag)
        raise
    return tag


def read_icn(mesh: SurfaceMesh) -> dict[int, float]:
    """Read freshly computed ICN, leaving unrelated views/element visibility intact.

    This is a measurement adapter, not an ICN acceptance threshold or CAD
    orientation check. Call only for a snapshot of the current Gmsh model.
    """
    return _read_plugin_metric(mesh, "ICN")


def read_ige(mesh: SurfaceMesh) -> dict[int, float]:
    """Read freshly computed IGE for the current surface mesh."""
    return _read_plugin_metric(mesh, "IGE")


def _read_plugin_metric(mesh: SurfaceMesh, metric: str) -> dict[int, float]:
    mesh.validate()
    assert_current(mesh)
    existing_views = set(map(int, gmsh.view.getTags()))
    visibility = gmsh.model.mesh.getVisibility(mesh.element_ids.tolist())
    try:
        options = {"DimensionOfElements": 2, "JacobianDeterminant": 0, "IGEMeasure": int(metric == "IGE"),
                   "ICNMeasure": int(metric == "ICN"), "CreateView": 1, "Recompute": 1,
                   "HidingThreshold": 99, "ThresholdGreater": 1}
        for key, value in options.items():
            gmsh.plugin.setNumber("AnalyseMeshQuality", key, value)
        gmsh.plugin.run("AnalyseMeshQuality")
        created = set(map(int, gmsh.view.getTags())) - existing_views
        if len(created) != 1:
            raise MeshBlocked(f"Plugin {metric} view 개수가 예상과 다릅니다")
        data_type, ids, values, _, components = gmsh.view.getModelData(created.pop(), 0)
        ids = list(map(int, ids))
        if data_type != "ElementData" or components != 1 or len(ids) != len(values):
            raise MeshBlocked(f"Plugin {metric} 결과 형식이 유효하지 않습니다")
        if len(ids) != len(set(ids)) or set(ids) != set(map(int, mesh.element_ids)):
            raise MeshBlocked(f"Plugin {metric} element ID가 현재 메쉬와 일치하지 않습니다")
        result = {}
        for element_id, value in zip(ids, values):
            if len(value) != 1 or not np.isfinite(value[0]) or value[0] <= 0 or value[0] > 1 + 1e-12:
                raise MeshBlocked(f"Plugin {metric} 값이 누락됐거나 유효 범위를 벗어났습니다")
            result[element_id] = float(value[0])
        return {int(tag): result[int(tag)] for tag in mesh.element_ids}
    except MeshBlocked:
        raise
    except Exception as exc:
        raise MeshBlocked(f"AnalyseMeshQuality {metric} 계산 실패: {exc}") from exc
    finally:
        for tag in set(map(int, gmsh.view.getTags())) - existing_views:
            gmsh.view.remove(tag)
        for value in set(map(int, visibility)):
            ids = mesh.element_ids[np.asarray(visibility) == value]
            gmsh.model.mesh.setVisibility(ids.tolist(), value)
