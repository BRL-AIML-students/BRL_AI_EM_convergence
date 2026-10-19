# BRL 표면 메쉬 생성기

이 저장소의 mesh generator는 `02_BRL_mesh_generator/`입니다. 기존 `01_mesh_generator/`와 브라우저 UI·NAS viewer·품질 보고서 경로를 새 ONELAB·CLI 공통 코어로 대체했습니다. 기존 입력 형식과 Action 번호는 이어받지 않습니다. 이전 구현은 Git 이력에 보존되어 있습니다.

## 설치·실행 (Windows x64)

```powershell
.\setup.bat
cd 02_BRL_mesh_generator
.\run_gmsh_ui.bat examples\plate.json
# CLI
.\run_cli.bat examples\ogive.json
```

처음 설치는 인터넷이 필요합니다. Python 3.12.14·uv 0.12.20·Gmsh 4.15.2와 고정 의존성을 준비하며 환경·캐시는 새 모듈 내부에 둡니다. 개발 도구는 루트에서 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev`로 설치합니다. 기존 루트 `.venv`는 새 구현에서 사용하지 않습니다.

ONELAB `BRL/00 Action`의 `Generate + publish NAS`는 생성·검사·필요한 개선·독립 NAS 읽기 검증을 실행합니다. 정상 산출물은 `outputs/run_<id>/mesh.nas` 한 파일입니다. 일반 Gmsh File/Export는 BRL의 발행 검사를 호출하지 않습니다.

- [사용자 guide: 생성 흐름·크기장·변수·Plugin·검사·발행·폴더 구조](02_BRL_mesh_generator/docs/mesh-generator-guide-ko.html)
- [설정·실행 빠른 안내](02_BRL_mesh_generator/README.md)
- [통합 검증·품질 정책·보관 기록](02_BRL_mesh_generator/docs/validation-ko.md)

Guide는 단일 HTML입니다. 로컬 브라우저로 열거나 GitHub에서 다운로드한 뒤 읽을 수 있습니다.

Native plate·ogive D/L/t와 STEP/IGES/BREP, 단위·PID, 특징별 크기장, CAD 편차 feedback, 품질·topology·법선·rollback 검사를 지원합니다. AR·최소각 등 기하 정책과 유한 표본 편차 검사는 EM 해석 정확도를 보증하지 않습니다. 자원 제한은 native 호출 전후의 협력적 검사입니다. UI 외관/마우스 시각 QA는 미실행입니다.

## 개발

`BRL.code-workspace`는 새 모듈을 엽니다. 자동 테스트는 모듈 폴더에서 실행합니다.

```powershell
New-Item -ItemType Directory -Force .cache\tests | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\local
```

앞으로 수정·PR·merge는 이 저장소를 대상으로 합니다. Merge와 branch 삭제는 기본적으로 사용자가 직접 진행하며, Codex는 명시적으로 요청받은 범위만 수행합니다. 이번 guide PR은 사용자가 merge까지 요청했으므로 merge commit으로 병합하고 branch는 보존합니다.
