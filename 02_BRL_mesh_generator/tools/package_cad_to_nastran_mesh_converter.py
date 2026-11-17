"""Build the minimal CAD-to-NAS distribution from the authoritative source."""
from __future__ import annotations
import argparse
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    '__init__.py', 'cad_deviation_sampling.py', 'cad_feature_size_rules.py',
    'cad_geometry_import.py', 'cad_geometry_preservation.py', 'cad_normal_verification.py',
    'configuration_value_validation.py', 'curvature_size_control.py', 'gmsh_quality_metrics.py',
    'mesh_adjacency_arrays.py', 'mesh_contract_inspection.py', 'mesh_generation_provenance.py',
    'mesh_generator_configuration.py', 'mesh_generator_errors.py', 'mesh_node_relocation.py',
    'mesh_quality_report.py', 'mesh_quality_settings.py', 'mesh_size_fields.py', 'mesh_size_settings.py',
    'mesh_validation_issues.py', 'nastran_mesh_io.py', 'surface_mesh_generation.py',
    'surface_mesh_snapshot.py', 'surface_mesh_topology.py', 'triangle_intersection_checks.py',
    'triangle_shape_checks.py',
)
FILES = ('README.md', 'convert_cad_to_nastran_surface_mesh.py', 'setup.ps1', 'pyproject.toml',
         'uv.lock', '.python-version', 'docs/01_프로그램구성과사용인터페이스.html',
         'docs/02_설정변수빠른참조.html', 'docs/03_메쉬생성원리와품질평가.html',
         'examples/mesh_quality_options.json', 'examples/cad/cylinder.brep',
         'examples/cad_to_nastran_mesh_options.json', 'examples/cad_to_nastran_conversion_jobs.json')

def build(output):
    output = Path(output).resolve()
    folder = output.parent / output.stem
    files = [Path(name) for name in FILES] + [Path('brl_mesh') / name for name in CORE]
    missing = [str(path) for path in files if not (ROOT / path).is_file()]
    if missing:
        raise ValueError('배포 필수 파일이 없습니다: ' + ', '.join(missing))
    if output.exists() or folder.exists():
        raise FileExistsError('배포 ZIP 또는 폴더가 이미 존재합니다')
    output.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which('git')
    commit, dirty = None, None
    if git:
        try:
            commit = subprocess.run([git, 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            dirty = bool(subprocess.run([git, 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = None, None
    version = (ROOT / 'brl_mesh/__init__.py').read_text(encoding='utf-8').split('__version__ = "')[1].split('"')[0]
    created_folder = False
    folder_identity = None
    created_archive = False
    archive_identity = None
    try:
        folder.mkdir()
        created_folder = True
        info = folder.stat()
        folder_identity = (info.st_dev, info.st_ino)
        for path in files:
            dest = folder / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, dest)
        # All three current-behavior manuals travel together with intact links.
        hashes = {path.as_posix(): hashlib.sha256((folder / path).read_bytes()).hexdigest() for path in files}
        (folder / 'ORIGIN.json').write_text(json.dumps({'commit': commit, 'working_tree_dirty': dirty, 'version': version, 'sha256': hashes}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with output.open('xb') as stream:
            created_archive = True
            info = output.stat()
            archive_identity = (info.st_dev, info.st_ino)
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(folder.rglob('*')):
                    if path.is_file():
                        archive.write(path, folder.name + '/' + path.relative_to(folder).as_posix())
    except Exception:
        # Only newly created paths are removed on failure.
        if created_archive and output.exists() and not output.is_symlink():
            info = output.stat()
            if (info.st_dev, info.st_ino) == archive_identity:
                output.unlink()
        if created_folder and folder.exists() and not folder.is_symlink() and folder.parent == output.parent and folder.name == output.stem:
            info = folder.stat()
            if (info.st_dev, info.st_ino) == folder_identity:
                shutil.rmtree(folder)
        raise
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CAD→NAS 최소 배포 폴더와 ZIP 생성')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'CAD_to_NAS.zip')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
