"""Isolated native jobs; the FLTK process never shares its Gmsh DLL with a job."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import gmsh

from .config import Configuration
from .cad import fingerprint
from .engine import boundary_state, generate, prepare_geometry, publish, scene_from_current
from .errors import MeshBlocked
from .improvement import improve
from .model import snapshot


def canonical(value):
    return json.loads(json.dumps(value))


def mesh_digest(mesh):
    digest = hashlib.sha256()
    for name in ('node_ids', 'coordinates', 'element_ids', 'connectivity', 'pids', 'surface_tags'):
        digest.update(getattr(mesh, name).tobytes())
    return digest.hexdigest()


def save_mesh(path):
    # All dimensions and parametric coordinates are needed for exact rollback.
    names = ('Mesh.MshFileVersion', 'Mesh.Binary', 'Mesh.SaveAll', 'Mesh.SaveParametric')
    old = [gmsh.option.getNumber(name) for name in names]
    try:
        for name, value in zip(names, (4.1, 1, 1, 1)):
            gmsh.option.setNumber(name, value)
        gmsh.write(str(path))
    finally:
        for name, value in zip(names, old):
            gmsh.option.setNumber(name, value)


def load_mesh(path, reference):
    # MSH imports append membership to existing Physical Groups in Gmsh 4.15.2.
    # Replace those groups with the serialized definitions, then check exactly.
    gmsh.model.removePhysicalGroups()
    gmsh.merge(str(path))
    if fingerprint() != reference.signature:
        raise MeshBlocked('mesh 전송 후 CAD 또는 Physical Group/PID가 일치하지 않습니다')


def write_json(path, value):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    pending.replace(path)


class NativeJob:
    def __init__(self, config, action, scene=None):
        self.config, self.action = config, action
        cache = Path(__file__).resolve().parent.parent / '.cache' / 'native-jobs'
        cache.mkdir(parents=True, exist_ok=True)
        self.storage = tempfile.TemporaryDirectory(prefix='job-', dir=cache)
        self.root = Path(self.storage.name)
        self.process = None
        self.original = None
        try:
            request = {'config': config.to_dict(), 'action': action}
            if action in (3, 4):
                if scene is None:
                    raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
                scene.require_current(config)
                self.original = snapshot(scene.membership)
                request.update(signature=canonical(scene.cad.signature), digest=scene.cad.digest,
                               boundary=canonical(scene.fixed_boundary), mesh_digest=mesh_digest(self.original))
                save_mesh(self.root / 'input.msh')
            write_json(self.root / 'request.json', request)
            self.log = (self.root / 'worker.log').open('wb')
            self.process = subprocess.Popen(
                [sys.executable, '-B', '-X', 'utf8', '-m', 'brl_mesh.native_job', str(self.root)],
                cwd=Path(__file__).resolve().parent.parent, stdout=self.log, stderr=self.log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception:
            self.close()
            raise

    def phase(self):
        paths = sorted(self.root.glob('phase-*.json'))
        return json.loads(paths[-1].read_text(encoding='utf-8')) if paths else 'Starting worker'

    def result(self):
        if self.process.poll() is None:
            return None
        path = self.root / 'result.json'
        if not path.exists():
            raise MeshBlocked(f'작업 프로세스가 완료 상태 없이 종료됐습니다 (exit={self.process.returncode})')
        result = json.loads(path.read_text(encoding='utf-8'))
        if self.process.returncode != 0 or result.get('status') != 'ok':
            raise MeshBlocked(result.get('reason', '작업 프로세스가 실패했습니다'))
        return result

    def adopt(self, result, scene):
        """Restore into fresh CAD, or update the unchanged current scene."""
        config = self.config
        if self.action in (1, 2):
            gmsh.clear()
            reference, sizing, curvature = prepare_geometry(config)
            if (canonical(reference.signature) != result['signature'] or reference.digest != result['digest']):
                raise MeshBlocked('작업 중 CAD 참조가 변경됐습니다. 다시 생성하세요')
        else:
            scene.require_current(config)
            from .model import assert_current
            assert_current(self.original)
            reference, sizing, curvature = scene.cad, scene.sizing, scene.curvature
        if self.action != 4:
            gmsh.model.mesh.clear()
            load_mesh(self.root / 'output.msh', reference)
            if canonical(boundary_state()) != result['boundary']:
                raise MeshBlocked('작업 결과의 CAD 경계 mesh 전송이 일치하지 않습니다')
            if self.action in (1, 2):
                scene = scene_from_current(config, reference, sizing, curvature)
        mesh = snapshot(scene.membership)
        if mesh_digest(mesh) != result['mesh_digest']:
            raise MeshBlocked('작업 결과의 좌표·연결·ID·PID 전송이 일치하지 않습니다')
        return scene, mesh

    def commit_publication(self, result):
        """Only a completed, independently validated NAS reaches the destination."""
        name = result.get('publication')
        if name is None:
            return ''
        # This name is generated by our worker, never interpreted as a path.
        if Path(name).name != name or not name.startswith('run_'):
            raise MeshBlocked('작업 결과의 발행 이름이 유효하지 않습니다')
        source = self.root / 'publication' / name / 'mesh.nas'
        if hashlib.sha256(source.read_bytes()).hexdigest() != result['nas_digest']:
            raise MeshBlocked('검증 이후 NAS가 변경됐습니다')
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=self.config.output_dir))
        try:
            shutil.copyfile(source, stage / 'mesh.nas')
            if hashlib.sha256((stage / 'mesh.nas').read_bytes()).hexdigest() != result['nas_digest']:
                raise MeshBlocked('NAS 전송 검증이 일치하지 않습니다')
            final = self.config.output_dir / name
            stage.rename(final)
            return str(final / 'mesh.nas')
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if hasattr(self, 'log'):
            self.log.close()
        self.storage.cleanup()


def execute(root):
    request = json.loads((root / 'request.json').read_text(encoding='utf-8'))
    config = replace(Configuration.from_dict(request['config']), output_dir=root / 'publication')
    action = request['action']
    if action not in (1, 2, 3, 4):
        raise MeshBlocked('지원하지 않는 작업입니다')
    phase_index = 0
    def phase(message):
        nonlocal phase_index
        phase_index += 1
        # Never replace a file the Windows UI may currently have open.
        write_json(root / f'phase-{phase_index:04d}.json', message)
    if action in (1, 2):
        phase('Generating mesh / CAD deviation')
        scene = generate(config)
    else:
        phase('Checking current CAD reference')
        reference, sizing, curvature = prepare_geometry(config)
        if (canonical(reference.signature) != request['signature'] or reference.digest != request['digest']):
            raise MeshBlocked('현재 CAD/source가 생성 참조와 일치하지 않습니다')
        load_mesh(root / 'input.msh', reference)
        if canonical(boundary_state()) != request['boundary']:
            raise MeshBlocked('현재 경계 mesh가 생성 참조와 일치하지 않습니다')
        scene = scene_from_current(config, reference, sizing, curvature)
        if mesh_digest(snapshot(scene.membership)) != request['mesh_digest']:
            raise MeshBlocked('현재 mesh 전송이 일치하지 않습니다')
    if action != 4:
        phase('Checking topology / normals / quality; improving if needed')
        prepared = improve(scene.membership, scene.contract, config.improvement)
        prepared.inspection.require_pass()
        mesh = prepared.mesh
        save_mesh(root / 'output.msh')
    else:
        mesh = snapshot(scene.membership)
    result = dict(status='ok', signature=canonical(scene.cad.signature), digest=scene.cad.digest,
                  boundary=canonical(scene.fixed_boundary), mesh_digest=mesh_digest(mesh))
    if action in (1, 4):
        phase('Rechecking mesh / validating NAS with independent reader')
        publication = publish(mesh, config, scene)
        result.update(publication=publication.nas_path.parent.name,
                      nas_digest=hashlib.sha256(publication.nas_path.read_bytes()).hexdigest())
    return result


def main():
    root = Path(sys.argv[1]).resolve()
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber('General.Terminal', 0)
    try:
        result, code = execute(root), 0
    except Exception as exc:
        result, code = {'status': 'blocked', 'reason': str(exc)}, 1
    finally:
        gmsh.finalize()
    write_json(root / 'result.json', result)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
