# BRL 표면 메쉬 생성기

이 저장소의 mesh generator는 `02_BRL_mesh_generator/`입니다. STEP / IGES / BREP CAD에서 삼각형 표면 메시를 생성하고, 검사·개선·독립 NAS 읽기 검증을 거쳐 `.nas` 파일로 저장합니다. MoM 해석은 사용자의 기존 코드에서 수행합니다.

## 설치·실행 (Windows x64)

전체 저장소를 영문 로컬 경로에 풀고 실행합니다. 처음 설치는 인터넷이 필요하며 환경·캐시는 모듈 내부에 둡니다.

```powershell
.\setup.bat
cd 02_BRL_mesh_generator
# 포함된 CAD를 NAS로 변환
.\run_cad_to_nastran_surface_mesh.bat --jobs examples\cad_to_nastran_conversion_jobs.json
# ONELAB UI (전체 저장소)
.\run_gmsh_onelab_mesh_interface.bat examples\plate.json
# JSON 기반 CLI
.\run_mesh_generator_command_line.bat examples\ogive.json
```

Python 3.12.14·Gmsh 4.15.2·NumPy 1.26.4·pyNastran 1.4.1과 고정 의존성을 사용합니다. 개발 도구는 루트에서 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev`로 설치합니다.

CAD→NAS 예제는 `outputs/cad-to-nas/cylinder.nas`를 생성하며 기존 출력은 덮어쓰지 않습니다. ONELAB `BRL/00 Action`의 `Generate + publish NAS`는 생성·검사·필요한 개선·독립 NAS 읽기 검증을 실행합니다. ONELAB·JSON CLI의 산출물은 `outputs/run_<형상>_<치수>_<id>/mesh.nas`입니다. 일반 Gmsh File/Export는 BRL의 발행 검사를 호출하지 않습니다.

- [CAD→NAS 시작하기와 Python 연동](02_BRL_mesh_generator/README.md)
- [사용방법과 설정](02_BRL_mesh_generator/docs/01_사용방법과설정.html)
- [구조와 코드 해설·파일명 대응표](02_BRL_mesh_generator/docs/02_구조와코드해설.html)
- [개발 검증과 변경 이력](02_BRL_mesh_generator/docs/03_개발검증과변경이력.html)

설명서는 각각 CSS·그림·수식을 내장한 단일 HTML입니다. 다운로드한 저장소에서 로컬 브라우저로 열어 읽습니다.

2026-11-16에 내부 모듈과 실행 파일을 역할 중심 이름으로 변경했습니다. 이전 import·실행 파일명은 지원하지 않습니다. 메쉬용 주파수는 MoM 변수와 독립인 `mesh_frequency_hz`로 지정하며, ICN·AR·최소각·radius ratio의 활성 여부와 기준값은 `quality`에서 각각 설정합니다. 메시 검사 통과는 MoM 해석의 정확도를 보증하지 않습니다.

## 개발

`BRL.code-workspace`는 새 모듈을 엽니다. 자동 테스트는 모듈 폴더에서 실행합니다.

```powershell
New-Item -ItemType Directory -Force .cache\tests | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\local
```

2026-11-16의 현재 작업 파일에서 전체 자동 테스트 673개가 통과했습니다. Python·명령행·실제 ONELAB에서 생성·저장을 확인했으며, 구체적인 조건과 한계는 개발 검증 설명서를 따릅니다. 환경·캐시·개인 결과 파일은 게시하지 않습니다.

수정·PR·merge는 이 저장소를 대상으로 합니다. Codex는 사용자가 명시적으로 요청한 범위에서 merge commit으로 병합하며, 병합 후 해당 PR의 원격 작업 branch와 대응 로컬 작업 branch를 삭제합니다.
