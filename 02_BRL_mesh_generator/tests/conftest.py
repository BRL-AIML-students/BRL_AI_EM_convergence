import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.model import SurfaceMesh


@pytest.fixture
def config(tmp_path):
    return Configuration.from_dict({
        'schema_version': 1,
        'geometry': {'kind': 'plate', 'length': 1, 'width': 1},
        'length_unit': 'mm', 'output_unit': 'mm',
        'mesh': {'target_size': 0.25}, 'output_dir': str(tmp_path / 'output'),
    })


@pytest.fixture
def square():
    return SurfaceMesh(np.array([10, 20, 30, 40]),
                       np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]]),
                       np.array([100, 200]), np.array([[10, 20, 30], [10, 30, 40]]),
                       np.ones(2, dtype=np.int64), np.full(2, 7, dtype=np.int64))
