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


def test_provenance_comments_round_trip_and_tampering_is_rejected(square, config, tmp_path, monkeypatch):
    import json
    from brl_mesh import provenance
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    metadata = json.loads(provenance.capture(config, None))
    path = tmp_path / 'mesh.nas'
    nas.write(path, square, 'mm', provenance=metadata)
    nas.validate(path, square, provenance=metadata)
    text = path.read_text(encoding='ascii')
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith('$ BRL-PROV 000000 '))
    lines[index] = lines[index][:-1] + ('A' if lines[index][-1] != 'A' else 'B')
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')
    with pytest.raises(MeshBlocked, match='provenance'):
        nas.validate(path, square, provenance=metadata)


def test_writer_without_provenance_remains_supported(square, tmp_path):
    path = tmp_path / 'plain.nas'
    nas.write(path, square, 'mm')
    nas.validate(path, square)
    assert '$ BRL-PROV' not in path.read_text(encoding='ascii')


def test_reader_rejects_self_consistent_unknown_schema_without_expected(square, tmp_path):
    import base64
    import hashlib
    import json
    path = tmp_path / 'bad.nas'
    nas.write(path, square, 'mm')
    payload = json.dumps({'anything': 1}, sort_keys=True, separators=(',', ':')).encode('ascii')
    encoded = base64.b64encode(payload).decode('ascii')
    comments = [f'$ BRL-PROV-SHA256 {hashlib.sha256(payload).hexdigest()}']
    comments += [f'$ BRL-PROV {i:06d} {encoded[i*48:(i+1)*48]}' for i in range((len(encoded)+47)//48)]
    path.write_text('\n'.join(comments) + '\n' + path.read_text(encoding='ascii'), encoding='ascii')
    with pytest.raises(MeshBlocked, match='provenance'):
        nas.validate(path, square)
