"""NAS free-field writer and strict + independent round-trip validation.

The legacy BRL GRID/CTRIA3/ENDDATA contract is retained; runtime code is independent.
"""
from __future__ import annotations

from pathlib import Path
import json

import numpy as np
from pyNastran.bdf.bdf import BDF

from .config import UNIT_METRES
from .errors import MeshBlocked
from .model import SurfaceMesh


def _real(value: float) -> str:
    text = format(float(value), '.17g')
    # pyNastran distinguishes integer tokens from real-valued GRID fields.
    return text if any(c in text for c in '.eE') else text + '.0'


def write(path: Path, mesh: SurfaceMesh, output_unit: str, *, geometry=None, length_unit=None) -> None:
    mesh.validate()
    if output_unit not in UNIT_METRES:
        raise MeshBlocked("NAS의 길이 단위가 유효하지 않습니다")
    # Exclusive creation also protects existing output if this function is called directly.
    with path.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(f'$ BRL surface mesh\n$ length unit: {output_unit}\n')
        if geometry is not None:
            stream.write('$ geometry input: '+json.dumps(geometry, ensure_ascii=True, sort_keys=True)+'\n')
            stream.write('$ geometry length unit: '+str(length_unit)+'\n')
        for node, point in zip(mesh.node_ids, mesh.coordinates):
            stream.write(f'GRID,{int(node)},,{",".join(_real(x) for x in point)}\n')
        for eid, pid, nodes in zip(mesh.element_ids, mesh.pids, mesh.connectivity):
            stream.write(f'CTRIA3,{int(eid)},{int(pid)},{",".join(str(int(n)) for n in nodes)}\n')
        stream.write('ENDDATA\n')


def validate(path: Path, expected: SurfaceMesh) -> None:
    expected.validate()
    nodes, elements = {}, {}
    ended = False
    try:
        for raw in path.read_text(encoding='ascii').splitlines():
            line = raw.strip()
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
        if not ended or sorted(nodes) != expected.node_ids.tolist() or sorted(elements) != expected.element_ids.tolist():
            raise MeshBlocked("NAS의 ENDDATA 또는 node/element ID가 일치하지 않습니다")
        if not np.array_equal(np.asarray([nodes[int(n)] for n in expected.node_ids]), expected.coordinates):
            raise MeshBlocked("NAS 좌표가 현재 메쉬와 일치하지 않습니다")
        for eid, pid, conn in zip(expected.element_ids, expected.pids, expected.connectivity):
            if elements[int(eid)] != (int(pid), conn.tolist()):
                raise MeshBlocked("NAS 연결 또는 PID가 현재 메쉬와 일치하지 않습니다")
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
