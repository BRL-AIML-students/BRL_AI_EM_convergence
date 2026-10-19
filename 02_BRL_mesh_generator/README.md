# 02_BRL_mesh_generator

Gmsh ONELAB·CLI에서 현재 설정으로 1차 삼각형 표면 메쉬를 생성하고, 필수 검사와 독립 읽기 검증을 통과한 NAS 한 건을 출력하는 새 프로젝트입니다.

## 현재 상태

2026-10-19: 1단계의 단순 판 생성·검사·검증된 NAS 출력과 Plugin ICN 읽기 adapter를 구현했습니다. 현재 지원 범위는 XY 평면의 단일 직사각형 판(+Z 기준 방향)입니다. 일반 CAD·ONELAB·개선/rollback·특징별 크기장·곡률 제어는 이후 단계입니다. 전체 생성기가 완료된 상태는 아닙니다.

- [재작성 계획](docs/rebuild-plan-ko.md)
- [기존 BRL 보관 기록](docs/archive-record-ko.md)
- [기존 통합 계획서](../99_archive/BRL_2026-10-19/docs/mesh-generator-refactor-plan-ko.md)
- [1단계 구현·검증 기록](docs/stage-1-validation-ko.md)

## 설치·실행

프로젝트 폴더의 PowerShell에서 실행합니다. 설치는 공식 uv release의 고정 SHA256을 확인하고, 프로젝트 안에 별도 Python·가상환경·캐시를 구성합니다.

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m brl_mesh examples\plate.json
# 같은 CLI를 실행하는 Windows launcher
.\run_cli.bat examples\plate.json
```

정상 시 `outputs/run_<id>/mesh.nas` 한 파일과 stdout의 짧은 상태 JSON을 제공합니다. NAS를 임시 파일로 쓰고 독립 pyNastran reader에서 좌표·ID·connectivity·PID 일치를 확인한 후 발행합니다. 실패한 임시 파일은 정리하고 기존 정상 결과를 보존합니다. 종료 코드는 정상 0, 입력/실행 오류 1, 검사 차단 2입니다.

`geometry.length/width/origin`은 `length_unit` 기준이며 `mesh.target_size`는 `output_unit` 기준의 요청 길이입니다. 예제는 100 × 60 mm 판에 10 mm 목표를 적용합니다. 목표 길이는 실제 모든 edge의 엄격한 상한이 아닙니다. 상대 `output_dir`는 설정 파일의 폴더를 기준으로 해석합니다. 미지원 geometry·알 수 없는 키·과거 controlled/compare 키는 명시적으로 거부합니다.

## 로컬 단계별 작업

각 단계는 `codex/rebuild-core`에서 로컬 파일 작성·검증·commit으로 진행합니다. 전체 구현·통합 검증 뒤 최종 GitHub PR을 준비하고, merge는 사용자 지시가 있을 때 수행합니다. 병합 성공을 확인한 뒤 해당 작업 branch를 로컬·원격에서 정리합니다.

## 테스트

```powershell
New-Item -ItemType Directory -Path .cache\tests -Force | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage1
```

Windows Gmsh DLL과 pytest의 기본 native FD capture 충돌을 피하도록 `--capture=sys`를 프로젝트 설정에 포함했습니다. 제품의 보고서·진단 파일 생성과 개발 테스트 기록은 구분합니다.

## 개발 원칙

새 구조에서 실행 흐름·설정·검사 반환값을 설계합니다. 기존 BRL의 런타임 모듈·가상환경을 참조하지 않습니다. 기존 코드는 검증할 동작과 재사용 후보를 확인하는 읽기 전용 자료로 취급합니다.

제품에는 웹 UI·서버·NAS viewer·조건 조합별 비교 생성·점수·등급·HTML/JSON 보고서·독립 진단 화면을 포함하지 않습니다. 생성·개선·정상 NAS 발행에 필요한 검사와 오류 설명은 유지합니다.

요소 형상 품질 계산은 `AnalyseMeshQuality`를 우선 활용 대상으로 삼고, BRL은 판정·개선 제어를 담당합니다. 연결/topology와 CAD/기준 방향 법선은 별도 검사합니다. AR·최소각 유지 또는 ICN 중심 전환은 사례 검증 후 확정하며, 모든 지표를 기본으로 중복 계산하지 않습니다. Plugin/API 자동화 경로의 선택 기준과 임시 view 정리·재검사·rollback 절차는 [재작성 계획](docs/rebuild-plan-ko.md)에 정리했습니다.

1단계 출력 경로는 기존 AR ≤ 3·최소각 ≥ 20° 운영 조건을 보존합니다. 이 두 값은 score wrapper 없이 출력 차단에만 사용합니다. ICN adapter는 element ID 대응·재계산·view/표시 상태 보존을 개발 테스트로 검증하고, 출력 경로에 별도의 ICN 차단 기준을 추가하지 않았습니다. 2단계에서 정책을 검증해 계산 경로를 확정합니다. 현재 검사 통과는 EM 정확도 보증이 아닙니다.
