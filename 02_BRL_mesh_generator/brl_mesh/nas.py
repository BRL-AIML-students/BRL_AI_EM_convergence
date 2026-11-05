"""NAS free-field writer and strict + independent round-trip validation.

The legacy BRL GRID/CTRIA3/ENDDATA contract is retained; runtime code is independent.
"""
from __future__ import annotations

from pathlib import Path
import json
import hashlib
import base64

import numpy as np

from .config import UNIT_METRES
from .errors import MeshBlocked
from .model import SurfaceMesh
from .provenance import canonical, validate_schema


def file_digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _real(value: float) -> str:
    text = format(float(value), '.17g')
    # pyNastran distinguishes integer tokens from real-valued GRID fields.
    return text if any(c in text for c in '.eE') else text + '.0'


def _provenance_lines(value):
    validate_schema(value)
    payload = canonical(value).encode('ascii')
    encoded = base64.b64encode(payload).decode('ascii')
    chunks = [encoded[i:i + 48] for i in range(0, len(encoded), 48)]
    return ([f'$ BRL-PROV-SHA256 {hashlib.sha256(payload).hexdigest()}'] +
            [f'$ BRL-PROV {index:06d} {chunk}' for index, chunk in enumerate(chunks)])


def write(path: Path, mesh: SurfaceMesh, output_unit: str, *, geometry=None, length_unit=None,
          provenance=None) -> None:
    mesh.validate()
    if output_unit not in UNIT_METRES:
        raise MeshBlocked("NAS의 길이 단위가 유효하지 않습니다")
    # Exclusive creation also protects existing output if this function is called directly.
    with path.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(f'$ BRL surface mesh\n$ length unit: {output_unit}\n')
        if geometry is not None:
            stream.write('$ geometry input: '+json.dumps(geometry, ensure_ascii=True, sort_keys=True)+'\n')
            stream.write('$ geometry length unit: '+str(length_unit)+'\n')
        if provenance is not None:
            for line in _provenance_lines(provenance):
                stream.write(line + '\n')
        for node, point in zip(mesh.node_ids, mesh.coordinates):
            stream.write(f'GRID,{int(node)},,{",".join(_real(x) for x in point)}\n')
        for eid, pid, nodes in zip(mesh.element_ids, mesh.pids, mesh.connectivity):
            stream.write(f'CTRIA3,{int(eid)},{int(pid)},{",".join(str(int(n)) for n in nodes)}\n')
        stream.write('ENDDATA\n')


def _validate_provenance(lines, expected):
    if not lines:
        if expected is not None:
            raise MeshBlocked('NAS provenance가 누락됐습니다')
        return
    try:
        chunks = [line.split(' ', 3)[3] for line in lines[1:]]
        payload = base64.b64decode(''.join(chunks), validate=True)
        value = json.loads(payload.decode('ascii'))
        if lines != _provenance_lines(value) or (expected is not None and value != expected):
            raise ValueError('provenance mismatch')
    except Exception as exc:
        raise MeshBlocked(f'NAS provenance가 손상됐거나 생성 참조와 일치하지 않습니다: {exc}') from exc


def _validate_cards(stream, expected: SurfaceMesh, provenance=None) -> None:
    nodes, elements = {}, {}
    ended = False
    provenance_lines = []
    for raw in stream:
        line = raw.strip()
        if line.startswith('$ BRL-PROV'):
            provenance_lines.append(line)
        if not line or line.startswith('$'):
            continue
        if ended:
            raise MeshBlocked("NAS ENDDATA 뒤에 데이터가 있습니다")
        fields = line.split(',')
        if len(fields) == 6 and fields[0] == 'GRID' and not fields[2].strip():
            node = int(fields[1])
            if node <= 0 or node in nodes:
                raise MeshBlocked("NAS node ID가 중복됐거나 유효하지 않습니다")
            nodes[node] = list(map(float, fields[3:]))
        elif len(fields) == 6 and fields[0] == 'CTRIA3':
            eid, pid, a, b, c = map(int, fields[1:])
            if eid <= 0 or eid in elements:
                raise MeshBlocked("NAS element ID가 중복됐거나 유효하지 않습니다")
            elements[eid] = (pid, [a, b, c])
        elif fields == ['ENDDATA']:
            ended = True
        else:
            raise MeshBlocked("NAS에 미지원 또는 손상된 card가 있습니다")
    _validate_provenance(provenance_lines, provenance)
    if not ended or sorted(nodes) != expected.node_ids.tolist() or sorted(elements) != expected.element_ids.tolist():
        raise MeshBlocked("NAS의 ENDDATA 또는 node/element ID가 일치하지 않습니다")
    if not np.array_equal(np.asarray([nodes[int(n)] for n in expected.node_ids]), expected.coordinates):
        raise MeshBlocked("NAS 좌표가 현재 메쉬와 일치하지 않습니다")
    for eid, pid, conn in zip(expected.element_ids, expected.pids, expected.connectivity):
        if elements[int(eid)] != (int(pid), conn.tolist()):
            raise MeshBlocked("NAS 연결 또는 PID가 현재 메쉬와 일치하지 않습니다")


def validate(path: Path, expected: SurfaceMesh, *, provenance=None) -> None:
    expected.validate()
    try:
        with path.open(encoding='ascii') as stream:
            _validate_cards(stream, expected, provenance)
        # Generate-only/UI processes do not need the independent reader's
        # transitive native libraries; publication always loads and runs it.
        from pyNastran.bdf.bdf import BDF
        reader = BDF(debug=False)
        reader.read_bdf(str(path), xref=False, punch=True, encoding='ascii')
        if set(reader.card_count) - {'GRID', 'CTRIA3', 'ENDDATA'}:
            raise MeshBlocked("독립 reader에서 미지원 card를 발견했습니다")
        if sorted(reader.nodes) != expected.node_ids.tolist() or sorted(reader.elements) != expected.element_ids.tolist():
            raise MeshBlocked("독립 reader의 ID가 현재 메쉬와 일치하지 않습니다")
        xyz = np.asarray([reader.nodes[int(n)].xyz for n in expected.node_ids])
        if not np.array_equal(xyz, expected.coordinates):
            raise MeshBlocked("독립 reader의 좌표가 현재 메쉬와 일치하지 않습니다")
        for eid, pid, conn in zip(expected.element_ids, expected.pids, expected.connectivity):
            element = reader.elements[int(eid)]
            if element.type != 'CTRIA3' or element.Pid() != int(pid) or element.node_ids != conn.tolist():
                raise MeshBlocked("독립 reader의 연결/PID가 현재 메쉬와 일치하지 않습니다")
    except MeshBlocked:
        raise
    except Exception as exc:
        raise MeshBlocked(f"NAS 독립 읽기 검증 실패: {exc}") from exc
