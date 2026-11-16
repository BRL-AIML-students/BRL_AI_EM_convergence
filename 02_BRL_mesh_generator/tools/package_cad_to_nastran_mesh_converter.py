"""Build an allowlisted source distribution; never package environments/caches."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output).resolve()
    files = [ROOT / name for name in ('README.md', 'convert_cad_to_nastran_surface_mesh.py', 'run_cad_to_nastran_surface_mesh.bat', 'setup.ps1',
                                     'pyproject.toml', 'uv.lock', '.python-version',
                                     'docs/01_사용방법과설정.html', 'docs/02_구조와코드해설.html',
                                     'docs/03_개발검증과변경이력.html', 'examples/mesh_quality_options.json',
                                     'examples/cad/cylinder.brep',
                                     'examples/cad_to_nastran_mesh_options.json', 'examples/cad_to_nastran_conversion_jobs.json')]
    files.extend(sorted((ROOT / 'brl_mesh').glob('*.py')))
    if any(not path.is_file() for path in files):
        raise ValueError('배포 필수 파일이 없습니다')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'CAD_to_NAS/' + path.relative_to(ROOT).as_posix())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CAD→NAS 소스 배포 ZIP 생성')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'CAD_to_NAS.zip')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
