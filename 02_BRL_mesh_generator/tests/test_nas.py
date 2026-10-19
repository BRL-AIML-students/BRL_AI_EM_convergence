import pytest

from brl_mesh import nas
from brl_mesh.errors import MeshBlocked


def test_independent_round_trip_noncontiguous_ids(square, tmp_path):
    path = tmp_path / 'mesh.nas'
    nas.write(path, square, 'mm')
    nas.validate(path, square)
    assert '$ length unit: mm' in path.read_text(encoding='ascii')
    with pytest.raises(FileExistsError):
        nas.write(path, square, 'mm')


@pytest.mark.parametrize('damage', ['coordinate', 'connectivity', 'pid', 'duplicate_grid', 'missing_end', 'after_end'])
def test_nas_corruption_is_rejected(square, tmp_path, damage):
    path = tmp_path / 'mesh.nas'
    nas.write(path, square, 'mm')
    text = path.read_text(encoding='ascii')
    if damage == 'coordinate':
        text = text.replace('GRID,10,,0.0,0.0,0.0', 'GRID,10,,0.1,0.0,0.0')
    elif damage == 'connectivity':
        text = text.replace('CTRIA3,100,1,10,20,30', 'CTRIA3,100,1,10,30,20')
    elif damage == 'pid':
        text = text.replace('CTRIA3,100,1,', 'CTRIA3,100,2,')
    elif damage == 'duplicate_grid':
        text = text.replace('ENDDATA', 'GRID,10,,0.0,0.0,0.0\nENDDATA')
    elif damage == 'missing_end':
        text = text.replace('ENDDATA', '')
    else:
        text += 'ENDDATA\n'
    path.write_text(text, encoding='ascii')
    with pytest.raises(MeshBlocked):
        nas.validate(path, square)
