from types import SimpleNamespace

import numpy as np

from brl_mesh.mesh_quality_report import write_report
from brl_mesh.mesh_quality_settings import QualitySettings


def test_ige_report_maps_element_ids_and_includes_all_values(tmp_path):
    policy = QualitySettings(icn_enabled=False, aspect_ratio_enabled=False,
                             minimum_angle_enabled=False, radius_ratio_enabled=False,
                             ige_enabled=True, ige_minimum=.5)
    mesh = SimpleNamespace(element_ids=np.array([9, 3]), node_ids=np.array([1, 2, 3, 4]))
    inspection = SimpleNamespace(shape=SimpleNamespace(settings=policy), ige={3: .2, 9: .8})
    config = SimpleNamespace(to_dict=lambda: {'geometry': {}})
    path = tmp_path / 'report.html'
    summary = write_report(path, mesh, inspection, config, 'cad-hash', 'nas-hash')
    report = path.read_text(encoding='utf-8')
    assert summary['metrics']['IGE']['violating_count'] == 1
    assert '<td>3</td><td>IGE</td>' in report
    assert '<td>9</td><td>IGE</td>' not in report
    assert 'IGE: 0.2' in report and 'ICN: 평가하지 않음' in report
    assert 'Radius ratio는 Gmsh 내장 gamma 지표' in report
