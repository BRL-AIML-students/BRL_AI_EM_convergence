import copy
import json

import pytest

from brl_mesh.config import Configuration
from brl_mesh.errors import ConfigurationError


BASE = {'schema_version': 1, 'geometry': {'kind': 'plate', 'length': 1, 'width': 1},
        'mesh': {'target_size': 0.1}}


@pytest.mark.parametrize('section,key,value', [
    (None, 'schema_version', True), (None, 'schema_version', 2),
    (None, 'output_unit', []), (None, 'output_dir', ''),
    ('geometry', 'length', 0), ('geometry', 'width', -1),
    ('geometry', 'length', True), ('geometry', 'width', float('nan')),
    ('geometry', 'origin', [0, 0]), ('geometry', 'kind', 'cad'),
    ('mesh', 'target_size', float('inf')), ('mesh', 'target_size', -0.5),
    ('mesh', 'controlled', True), (None, 'compare', True),
])
def test_invalid_and_retired_inputs_are_rejected(section, key, value):
    data = copy.deepcopy(BASE)
    (data if section is None else data[section])[key] = value
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(data)


def test_paths_are_relative_to_config_not_working_directory(tmp_path):
    folder = tmp_path / '설정'
    folder.mkdir()
    path = folder / 'plate.json'
    path.write_text(json.dumps(BASE | {'output_dir': '../result'}), encoding='utf-8')
    assert Configuration.load(path).output_dir == tmp_path / 'result'


def test_duplicate_json_key_is_not_silently_overwritten(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"schema_version":1,"schema_version":2}', encoding='utf-8')
    with pytest.raises(ConfigurationError, match='중복'):
        Configuration.load(path)


@pytest.mark.parametrize('settings', [
    {'enabled': 1}, {'max_passes': True}, {'max_passes': -1}, {'max_passes': 11},
    {'max_passes': 1.5}, {'methods': ['Smooth']},
])
def test_invalid_improvement_controls_are_rejected(settings):
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(BASE | {'improvement': settings})
