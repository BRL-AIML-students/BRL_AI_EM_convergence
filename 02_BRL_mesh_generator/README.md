# 02_BRL_mesh_generator

Gmsh ONELAB·CLI에서 현재 설정으로 1차 삼각형 표면 메쉬를 생성하고, 필수 검사와 독립 읽기 검증을 통과한 NAS 한 건을 출력하는 새 프로젝트입니다.

## 현재 상태

2026-10-19: 0–3단계의 독립 코어·품질/rollback·STEP/IGES/BREP 입력·native ONELAB 연결을 구현했습니다. 직접 생성하는 primitive는 현재 XY 평면의 직사각형 판(+Z)이며, CAD 파일에서는 solid와 열린 sheet 및 mixed BREP의 독립 curve/point를 읽습니다. 특징별 크기장·곡률/자원 제어·통합 검증은 4–6단계입니다.

- [재작성 계획](docs/rebuild-plan-ko.md)
- [기존 BRL 보관 기록](docs/archive-record-ko.md)
- [기존 통합 계획서](../99_archive/BRL_2026-10-19/docs/mesh-generator-refactor-plan-ko.md)
- [1단계 구현·검증 기록](docs/stage-1-validation-ko.md)
- [2단계 구현·검증 기록과 품질 정책 결정](docs/stage-2-validation-ko.md)
- [3단계 CAD·ONELAB 검증 기록](docs/stage-3-validation-ko.md)

## 설치·실행

프로젝트 폴더의 PowerShell에서 실행합니다. 설치는 공식 uv release의 고정 SHA256을 확인하고, 프로젝트 안에 별도 Python·가상환경·캐시를 구성합니다.

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m brl_mesh examples\plate.json
# 같은 CLI를 실행하는 Windows launcher
.\run_cli.bat examples\plate.json
# solid + sheet + 독립 curve/point를 포함한 BREP 예제
.\run_cli.bat examples\mixed_brep.json
# native Gmsh 창과 ONELAB
.\run_gmsh_ui.bat examples\plate.json
```

정상 시 `outputs/run_<id>/mesh.nas` 한 파일과 stdout의 짧은 상태 JSON을 제공합니다. NAS를 임시 파일로 쓰고 독립 pyNastran reader에서 좌표·ID·connectivity·PID 일치를 확인한 후 발행합니다. 실패한 임시 파일은 정리하고 기존 정상 결과를 보존합니다. 종료 코드는 정상 0, 입력/실행 오류 1, 검사 차단 2입니다.

`geometry.length/width/origin`은 `length_unit` 기준이며 `mesh.target_size`는 `output_unit` 기준의 요청 길이입니다. 예제는 100 × 60 mm 판에 10 mm 목표를 적용합니다. 목표 길이는 실제 모든 edge의 엄격한 상한이 아닙니다. 상대 `output_dir`는 설정 파일의 폴더를 기준으로 해석합니다. 알 수 없는 geometry·설정 키·과거 controlled/compare 키는 명시적으로 거부합니다.

`improvement.enabled`는 형상 불량이 있을 때 노드 재배치를 시도할지 정합니다. 기본값은 true, `max_passes` 기본값은 3(허용 범위 0–10)입니다. 예를 들어 false이면 재배치를 하지 않지만 필수 검사는 그대로 수행하고 불량 NAS 발행을 차단합니다. topology·법선·필수 계산에 문제가 있으면 재배치를 시작하지 않습니다. 정상 메쉬를 불필요하게 바꾸지 않으며 개선 전후 파일을 따로 만들지 않습니다.

## ONELAB 사용

`run_gmsh_ui.bat`로 연 창에서 ONELAB의 `BRL/00 Action`을 `Generate + publish NAS`로 선택하면 생성·필수 검사·필요한 개선·독립 NAS 검증까지 한 번 실행합니다. `Idle` 상태에서는 생성하지 않습니다. 완료 후 `BRL/02 NAS path`에 경로가 표시됩니다. 브라우저나 별도 ONELAB 프로그램 설치는 사용하지 않습니다.

단계를 나누려면 `Generate mesh` → 필요한 경우 `Improve current mesh` → `Publish current mesh`를 선택합니다. `Close` 또는 창 닫기로 종료합니다. Action은 소비 후 `Idle`로 돌아가므로 idle polling으로 NAS를 중복 발행하지 않습니다. native Gmsh의 일반 File/Export는 BRL 검사를 호출하지 않으므로 검증된 NAS는 이 Action 경로로 발행합니다.

`Geometry`, CAD 경로 또는 판 치수, 입력/출력 단위, 목표 크기, 개선 여부/횟수, 출력 폴더를 조정할 수 있습니다. 판의 방향은 +Z이며 CAD sheet 방향 제어는 CAD를 선택했을 때 표시됩니다. 크기와 개선 설정은 CLI와 같은 schema 검증을 거칩니다. CAD·설정·PID가 바뀌면 재생성이 필요합니다. 수동으로 바꾼 현재 mesh는 이전 검사 결과를 폐기하고 다음 Action에서 새로 검사하며, point/curve 경계 mesh가 바뀌면 재생성을 요구합니다.

## CAD·단위·방향

`geometry.kind="cad"`와 `geometry.path`를 지정합니다. 상대 CAD 경로와 상대 출력 폴더는 JSON 파일의 위치를 기준으로 합니다. `.step/.stp/.iges/.igs/.brep`를 대소문자와 관계없이 지원합니다.

| 입력 | 단위 적용 |
|---|---|
| plate·BREP | `length_unit`에서 `output_unit`으로 한 번 변환 |
| STEP·IGES | 파일에 저장된 단위를 `output_unit`으로 변환; `length_unit`을 중복 적용하지 않음 |
| `mesh.target_size`·`geometry.protected_gap` | 이미 `output_unit` 기준인 요청값 |

예를 들어 1000 mm 길이의 BREP를 `length_unit="mm"`, `output_unit="m"`로 읽으면 길이는 1 m입니다. 목표 250 mm는 `target_size=0.25`로 입력합니다. BREP 전체 compound를 import 시 변환하여 solid 경계뿐 아니라 독립 sheet·curve·point도 보존하며 surface tag가 단위 변경 때문에 바뀌지 않게 합니다. NAS에는 표면 삼각형과 그 참조 node만 포함합니다.

solid 경계는 CAD의 바깥 방향을 검사합니다. 열린 sheet는 `geometry.sheet_normal=1` 또는 `-1`로 CAD parameter normal의 기준 방향을 명시합니다. 면별 설정은 `sheet_normals={"7": -1}`처럼 surface tag별로 지정하며, 면별 값이 공통 `sheet_normal`보다 우선합니다. 필요한 방향이 빠지거나 solid 경계를 sheet로 지정하면 차단합니다. 음의 기준은 생성 winding에 적용하고 최종 현재 mesh에서도 다시 검사합니다.

PID는 변환 후 CAD surface tag와 같고 Physical Group으로 관리합니다. 재질 번호가 아니며 CAD를 수정하거나 Gmsh build가 바뀌어도 같은 tag가 유지된다는 보장은 없습니다. 고급 면별 방향과 `separated_surfaces`/`protected_gap`은 시작 JSON에 지정하며 ONELAB에서도 그 설정을 유지합니다. `separated_surfaces`는 공유 CAD 경계가 없는 surface 쌍에 대한 분리 의도입니다. `protected_gap`은 기존 node/edge 근접 검사의 tolerance 충돌 판정에 사용하며, 최소 간극 전체를 측정하거나 gap size field를 생성하는 기능은 4단계입니다.

## 로컬 단계별 작업

각 단계는 `codex/rebuild-core`에서 로컬 파일 작성·검증·commit으로 진행합니다. 전체 구현·통합 검증 뒤 최종 GitHub PR을 준비하고, merge는 사용자 지시가 있을 때 수행합니다. 병합 성공을 확인한 뒤 해당 작업 branch를 로컬·원격에서 정리합니다.

## 테스트

```powershell
New-Item -ItemType Directory -Path .cache\tests -Force | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage3
```

Windows Gmsh DLL과 pytest의 기본 native FD capture 충돌을 피하도록 `--capture=sys`를 프로젝트 설정에 포함했습니다. 제품의 보고서·진단 파일 생성과 개발 테스트 기록은 구분합니다.

## 개발 원칙

새 구조에서 실행 흐름·설정·검사 반환값을 설계합니다. 기존 BRL의 런타임 모듈·가상환경을 참조하지 않습니다. 기존 코드는 검증할 동작과 재사용 후보를 확인하는 읽기 전용 자료로 취급합니다.

제품에는 웹 UI·서버·NAS viewer·조건 조합별 비교 생성·점수·등급·HTML/JSON 보고서·독립 진단 화면을 포함하지 않습니다. 생성·개선·정상 NAS 발행에 필요한 검사와 오류 설명은 유지합니다.

`AnalyseMeshQuality`에서 ICN만 계산하여 유효한 결과 확인과 개선 후보의 수용 판단에 사용합니다. 연결/topology와 CAD/기준 방향 법선은 별도 검사합니다. 임시 view는 ID별 결과를 읽은 뒤 성공·실패 모두에서 정리하고 표시 상태를 보존합니다. 메쉬 변경 후 재계산하며 이전 snapshot으로 새 결과를 판정하거나 발행하지 않습니다.

2단계의 104개 삼각형 비교에서 기존 판정과 ICN 값의 수용/거부 범위가 겹쳤습니다. 따라서 AR ≤ 3·최소각 ≥ 20°는 기존 발행 기준으로 유지하고 ICN 임계값으로 임의 변환하지 않습니다. IGE·Jacobian measure를 추가로 켜거나 점수 구조를 복원하지 않습니다. 개선은 위반 감소 또는 최소 ICN 상승과 함께 기존 형상·기하·크기·gradation 조건의 비악화를 요구합니다. 연결·분류가 유지된 후보만 정확한 좌표/parameter rollback을 허용하며, 구조 변경이나 복구 실패 시 발행을 차단합니다. 현재 검사 통과는 EM 정확도 보증이 아닙니다.
