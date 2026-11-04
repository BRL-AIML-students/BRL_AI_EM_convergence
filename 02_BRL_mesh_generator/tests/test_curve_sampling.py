from types import SimpleNamespace
import math

import gmsh
import numpy as np
import pytest

from brl_mesh.errors import MeshBlocked
from brl_mesh.sizing import curve_sampling


SETTINGS = SimpleNamespace(sampling_fraction=.25)


def mock_curve(monkeypatch, *, mass=1., bounds=(0., 1.), value=None):
    monkeypatch.setattr(gmsh.model.occ, 'getMass', lambda *args: mass)
    monkeypatch.setattr(gmsh.model, 'getParametrizationBounds',
                        lambda *args: ([bounds[0]], [bounds[1]]))
    if value is None:
        value = lambda t: np.column_stack([t, np.zeros((len(t), 2))]).ravel()
    monkeypatch.setattr(gmsh.model, 'getValue', lambda dim, tag, t: value(t))


@pytest.mark.parametrize('kind', ['circle', 'spline'])
def test_actual_curve_sampling_preserves_original_chord_criteria(kind):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        if kind == 'circle':
            tag = gmsh.model.occ.addCircle(0, 0, 0, 1)
        else:
            nodes = [gmsh.model.occ.addPoint(*p) for p in
                     [(0, 0, 0), (.01, .6, 0), (2, .8, 0), (3, 0, 0)]]
            tag = gmsh.model.occ.addSpline(nodes)
        gmsh.model.occ.synchronize()
        spacing = .1
        mass = gmsh.model.occ.getMass(1, tag)
        low, high = gmsh.model.getParametrizationBounds(1, tag)
        expected = max(8, math.ceil(2*mass/spacing)+2)
        while True:
            xyz = np.asarray(gmsh.model.getValue(1, tag, np.linspace(low[0], high[0], expected))).reshape(-1, 3)
            lengths = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
            if lengths.max() <= spacing and lengths.sum() >= .999*mass:
                break
            expected *= 2
        assert curve_sampling([tag], .4, 0, .4, SETTINGS) == expected
    finally:
        gmsh.finalize()


def test_nonuniform_parameter_curve_can_need_later_refinement(monkeypatch):
    calls = []
    def value(t):
        calls.append(len(t))
        return np.column_stack([t**3, np.zeros((len(t), 2))]).ravel()
    mock_curve(monkeypatch, value=value)
    count = curve_sampling([1], 1, 0, 1, SETTINGS)
    assert calls == [10, 20]
    assert count == 20


def test_equal_chord_coverage_plateau_does_not_stop_late_convergence(monkeypatch):
    calls = []
    def value(t):
        calls.append(len(t))
        scale = .5 if len(calls) < 3 else 1.
        return np.column_stack([scale*t, np.zeros((len(t), 2))]).ravel()
    mock_curve(monkeypatch, value=value)
    assert curve_sampling([1], 1, 0, 1, SETTINGS) == 40
    assert calls == [10, 20, 40]


@pytest.mark.parametrize('missing_length', [False, True])
def test_exhausted_float_parameter_domain_blocks_unattainable_sampling(monkeypatch, missing_length):
    high = np.nextafter(1., np.inf)
    def value(t):
        x = np.zeros(len(t)) if missing_length else (t != 1.).astype(float)
        return np.column_stack([x, np.zeros((len(t), 2))]).ravel()
    mock_curve(monkeypatch, bounds=(1., high), value=value)
    with pytest.raises(MeshBlocked, match='sampling_precision_conflict.*curve 1'):
        curve_sampling([1], 1, 0, 1, SETTINGS)


@pytest.mark.parametrize('invalid', ['nan_mass', 'zero_mass', 'infinite_bounds', 'reversed_bounds',
                                    'missing_coordinates', 'nonfinite_coordinates', 'norm_overflow',
                                    'parameter_grid_overflow', 'api_failure'])
def test_invalid_curve_api_data_blocks_explicitly(monkeypatch, invalid):
    values = {}
    if invalid == 'nan_mass': values['mass'] = np.nan
    elif invalid == 'zero_mass': values['mass'] = 0.
    elif invalid == 'infinite_bounds': values['bounds'] = (0., np.inf)
    elif invalid == 'reversed_bounds': values['bounds'] = (1., 0.)
    elif invalid == 'missing_coordinates': values['value'] = lambda t: np.zeros((len(t)-1, 3))
    elif invalid == 'nonfinite_coordinates': values['value'] = lambda t: np.full((len(t), 3), np.nan)
    elif invalid == 'norm_overflow':
        values['value'] = lambda t: np.column_stack([t*1e200, np.zeros((len(t), 2))])
    elif invalid == 'parameter_grid_overflow':
        values['bounds'] = (-np.finfo(float).max, np.finfo(float).max)
        values['value'] = lambda t: pytest.fail('invalid parameter grid must not enter CAD API')
    else:
        def unavailable(t):
            raise RuntimeError('CAD unavailable')
        values['value'] = unavailable
    mock_curve(monkeypatch, **values)
    with pytest.raises(MeshBlocked, match='sampling_incomplete'):
        curve_sampling([1], 1, 0, 1, SETTINGS)
