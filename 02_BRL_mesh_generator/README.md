# BRL 표면 메쉬 생성기

Gmsh ONELAB·CLI에서 1차 삼각형 표면 메쉬를 생성하고, 필수 검사와 독립 NAS 읽기 검증을 통과한 파일 한 건을 발행합니다.

- **[사용자 guide: 흐름·크기장·변수·Plugin·검사·발행·폴더 구조](docs/mesh-generator-guide-ko.html)**
- [개발 검증·품질 정책·보관 및 GitHub 기록](docs/validation-ko.md)

Guide는 외부 자산 없이 읽을 수 있는 단일 HTML입니다. 로컬 브라우저로 여세요. GitHub에서는 HTML을 다운로드한 뒤 열 수 있습니다. 변수 이름은 Ctrl+F로 찾을 수 있습니다.

## 설치·실행

이 모듈 폴더에서 실행합니다. 설치는 Windows x64, 최초 인터넷 연결을 필요로 하며 Python 3.12.14·uv 0.12.20·고정 의존성을 프로젝트 내부에 구성합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev
.\run_gmsh_ui.bat examples\plate.json
# 또는 CLI
.\run_cli.bat examples\ogive.json
```

ONELAB의 `BRL/00 Action`에서 `Generate + publish NAS`를 선택하고 `BRL/01 Status`와 `BRL/02 NAS path`를 확인합니다. `Generate mesh`는 검사·필요한 개선까지 수행하지만 NAS는 쓰지 않습니다. `Publish current mesh`는 현재 메쉬를 재검사하고 발행합니다. 일반 Gmsh File/Export는 BRL 발행 검사를 호출하지 않습니다.

정상 결과는 `outputs/run_<형상>_<치수>_<id>/mesh.nas` 한 파일입니다. CLI는 정상 0·입력/실행 오류 1·검사 차단 2를 반환합니다. Native plate·ogive·sphere·cube·cylinder·dihedral과 STEP/IGES/BREP를 지원합니다. 형상 정의·파라미터별 그림·단위·기본값은 guide의 4장을 확인하세요. 새 입력 예제는 `examples/sphere.json`, `cube.json`, `cylinder_native.json`, `dihedral.json`이며 기존 `cylinder.json`은 CAD import 예제입니다.

D=50 mm, L=100 mm, t=0 ogive의 곡률 편차 0.01 mm 설정은 `examples/ogive_50x100.json`에 있습니다. `run_gmsh_ui.bat examples\ogive_50x100.json`으로 열고 `Generate + publish NAS`를 실행하세요. 생성 완료 시 새 메쉬 전체를 화면에 맞추며 NAS 주석에 입력 형상과 단위를 기록합니다.

## 개발과 관리

```powershell
New-Item -ItemType Directory -Force .cache\tests | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\local
```

의존성은 `uv.lock`으로 고정합니다. 환경과 `.git`를 임의 이동하지 말고 guide의 폴더 설명을 참고하세요. 현재 `.cache/github-delivery`는 별도 Git checkout이므로 단순 캐시처럼 전체 삭제하지 않습니다.

GitHub 대상은 [BRL_AI_EM_convergence](https://github.com/BRL-AIML-students/BRL_AI_EM_convergence), 저장소 안의 모듈 경로는 `02_BRL_mesh_generator/`입니다. Codex는 명시적으로 요청받은 범위에서 merge하며, merge까지 요청받으면 병합 후 해당 작업 branch를 삭제합니다.
