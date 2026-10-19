# 02_BRL_mesh_generator

Gmsh ONELAB·CLI에서 현재 설정으로 1차 삼각형 표면 메쉬를 생성하고, 필수 검사와 독립 읽기 검증을 통과한 NAS 한 건을 출력하는 새 프로젝트입니다.

## 현재 상태

2026-10-20: 0–6단계의 로컬 코어와 자동 통합 검증을 완료했습니다. native plate·ogive D/L/t, STEP/IGES/BREP, 공통 ONELAB·CLI, 특징별 크기장, 편차 feedback, 품질·topology·법선·rollback, 독립 NAS 검증을 연결했습니다. GitHub 대상은 [BRL_AI_EM_convergence](https://github.com/BRL-AIML-students/BRL_AI_EM_convergence)이며 기존 구현을 새 구현으로 교체하는 최종 PR을 준비합니다. Merge는 별도 사용자 지시에 따릅니다. native UI의 실제 event loop·Action 발행은 검증했고 마우스 조작·widget 외관의 시각 QA는 미실행입니다.

- [재작성 계획](docs/rebuild-plan-ko.md)
- [기존 BRL 보관 기록](docs/archive-record-ko.md)
- 기존 통합 계획서는 로컬 보관본 `99_archive/BRL_2026-10-19/docs/mesh-generator-refactor-plan-ko.md`에 있습니다. GitHub의 현재 구현 범위는 아래 재작성 계획을 따릅니다.
- [1단계 구현·검증 기록](docs/stage-1-validation-ko.md)
- [2단계 구현·검증 기록과 품질 정책 결정](docs/stage-2-validation-ko.md)
- [3단계 CAD·ONELAB 검증 기록](docs/stage-3-validation-ko.md)
- [4단계 특징별 크기장 검증 기록](docs/stage-4-validation-ko.md)
- [5단계 곡률·편차·자원 검증 기록](docs/stage-5-validation-ko.md)
- [6단계 native ogive·통합 검증 기록](docs/stage-6-validation-ko.md)
- [최종 GitHub 전달 준비](docs/github-delivery-ko.md)

## 설치·실행

프로젝트 폴더의 PowerShell에서 실행합니다. 설치는 공식 uv release의 고정 SHA256을 확인하고, 프로젝트 안에 별도 Python·가상환경·캐시를 구성합니다.

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m brl_mesh examples\plate.json
# 같은 CLI를 실행하는 Windows launcher
.\run_cli.bat examples\plate.json
# solid + sheet + 독립 curve/point를 포함한 BREP 예제
.\run_cli.bat examples\mixed_brep.json
# 폭 기반·분리 간극 기반 크기장
.\run_cli.bat examples\thin_plate.json
.\run_cli.bat examples\gaps.json
# 곡면 편차 feedback / 원당 223 분할 요구
.\run_cli.bat examples\cylinder.json
.\run_cli.bat examples\circle_223.json
# native ogive: 열린 sheet / 유한 두께 solid
.\run_cli.bat examples\ogive.json
.\run_cli.bat examples\ogive_wall.json
# native Gmsh 창과 ONELAB
.\run_gmsh_ui.bat examples\plate.json
```

정상 시 `outputs/run_<id>/mesh.nas` 한 파일과 stdout의 짧은 상태 JSON을 제공합니다. NAS를 임시 파일로 쓰고 독립 pyNastran reader에서 좌표·ID·connectivity·PID 일치를 확인한 후 발행합니다. 실패한 임시 파일은 정리하고 기존 정상 결과를 보존합니다. 종료 코드는 정상 0, 입력/실행 오류 1, 검사 차단 2입니다.

`geometry.length/width/origin`은 `length_unit` 기준이며 `mesh.target_size`는 `output_unit` 기준의 전역 요청 상한입니다. 예제는 100 × 60 mm 판에 10 mm 목표를 적용합니다. 목표 길이는 실제 모든 edge의 엄격한 상한이 아닙니다. 상대 `output_dir`는 설정 파일의 폴더를 기준으로 해석합니다. 알 수 없는 geometry·설정 키·과거 controlled/compare 키는 명시적으로 거부합니다.

`improvement.enabled`는 형상 불량이 있을 때 노드 재배치를 시도할지 정합니다. 기본값은 true, `max_passes` 기본값은 3(허용 범위 0–10)입니다. 예를 들어 false이면 재배치를 하지 않지만 필수 검사는 그대로 수행하고 불량 NAS 발행을 차단합니다. topology·법선·필수 계산에 문제가 있으면 재배치를 시작하지 않습니다. 정상 메쉬를 불필요하게 바꾸지 않으며 개선 전후 파일을 따로 만들지 않습니다.

## ONELAB 사용

`run_gmsh_ui.bat`로 연 창에서 ONELAB의 `BRL/00 Action`을 `Generate + publish NAS`로 선택하면 생성·필수 검사·필요한 개선·독립 NAS 검증까지 한 번 실행합니다. `Idle` 상태에서는 생성하지 않습니다. 완료 후 `BRL/02 NAS path`에 경로가 표시됩니다. 브라우저나 별도 ONELAB 프로그램 설치는 사용하지 않습니다.

단계를 나누려면 `Generate mesh` → 필요한 경우 `Improve current mesh` → `Publish current mesh`를 선택합니다. `Close` 또는 창 닫기로 종료합니다. Action은 소비 후 `Idle`로 돌아가므로 idle polling으로 NAS를 중복 발행하지 않습니다. native Gmsh의 일반 File/Export는 BRL 검사를 호출하지 않으므로 검증된 NAS는 이 Action 경로로 발행합니다.

`Geometry`, CAD 경로 또는 판 치수, 입력/출력 단위, 목표 크기, 개선 여부/횟수, 출력 폴더를 조정할 수 있습니다. 판의 방향은 +Z이며 CAD sheet 방향 제어는 CAD를 선택했을 때 표시됩니다. 크기와 개선 설정은 CLI와 같은 schema 검증을 거칩니다. CAD·설정·PID가 바뀌면 재생성이 필요합니다. 수동으로 바꾼 현재 mesh는 이전 검사 결과를 폐기하고 다음 Action에서 새로 검사하며, point/curve 경계 mesh가 바뀌면 재생성을 요구합니다.

## CAD·단위·방향

`geometry.kind="cad"`와 `geometry.path`를 지정합니다. 상대 CAD 경로와 상대 출력 폴더는 JSON 파일의 위치를 기준으로 합니다. `.step/.stp/.iges/.igs/.brep`를 대소문자와 관계없이 지원합니다.

| 입력 | 단위 적용 |
|---|---|
| plate·ogive·BREP | `length_unit`에서 `output_unit`으로 한 번 변환 |
| STEP·IGES | 파일에 저장된 단위를 `output_unit`으로 변환; `length_unit`을 중복 적용하지 않음 |
| `mesh.target_size`·`geometry.protected_gap` | 이미 `output_unit` 기준인 요청값 |

예를 들어 1000 mm 길이의 BREP를 `length_unit="mm"`, `output_unit="m"`로 읽으면 길이는 1 m입니다. 목표 250 mm는 `target_size=0.25`로 입력합니다. BREP 전체 compound를 import 시 변환하여 solid 경계뿐 아니라 독립 sheet·curve·point도 보존하며 surface tag가 단위 변경 때문에 바뀌지 않게 합니다. NAS에는 표면 삼각형과 그 참조 node만 포함합니다.

solid 경계는 CAD의 바깥 방향을 검사합니다. 열린 sheet는 `geometry.sheet_normal=1` 또는 `-1`로 CAD parameter normal의 기준 방향을 명시합니다. 면별 설정은 `sheet_normals={"7": -1}`처럼 surface tag별로 지정하며, 면별 값이 공통 `sheet_normal`보다 우선합니다. 필요한 방향이 빠지거나 solid 경계를 sheet로 지정하면 차단합니다. 음의 기준은 생성 winding에 적용하고 최종 현재 mesh에서도 다시 검사합니다.

PID는 변환 후 CAD surface tag와 같고 Physical Group으로 관리합니다. 재질 번호가 아니며 CAD를 수정하거나 Gmsh build가 바뀌어도 같은 tag가 유지된다는 보장은 없습니다. 고급 면별 방향과 `separated_surfaces`/`protected_gap`은 시작 JSON에 지정하며 ONELAB에서도 그 설정을 유지합니다. `separated_surfaces`는 공유 CAD 경계가 없는 surface 쌍에 대한 분리 의도입니다. `protected_gap`은 기존 node/edge 근접 검사의 tolerance 충돌 판정에 사용하며, 별도 `mesh.local.gaps.enabled=true`가 분리 CAD 사이의 최소 거리 측정과 gap size field를 활성화합니다. 전체 공간의 최소 간극 보증이나 같은 face의 접힘 측정은 하지 않습니다.

### Native ogive

`run_gmsh_ui.bat examples/ogive.json`으로 시작하고 `Generate + publish NAS`를 선택합니다. `Geometry=ogive`에서 `Ogive diameter D`, `Ogive length L`, `Ogive thickness t`, `Origin X/Y/Z`를 조정합니다. D/L/t/origin은 `Length unit (native and BREP)`, 크기·허용 편차는 `Output unit` 기준입니다. CLI도 같은 JSON을 받습니다.

```json
"geometry": {"kind": "ogive", "diameter": 2, "length": 3,
             "thickness": 0.2, "origin": [0, 0, 0]}
```

D는 base 외경, L은 base부터 +Z tip까지의 길이입니다. t=0이면 base가 열린 sheet 두 면, t>0이면 내측 원호를 같은 중심에서 t만큼 offset한 한 solid의 경계 표면을 생성합니다. base 내경은 D−2t이며 내부 tip은 외부 tip보다 낮습니다. 예를 들어 D=2·L=3·t=.2 mm이면 생성 원호 R=5 mm, 내부 R=4.8 mm, 내부 tip 높이 약 2.6533 mm입니다.

지원 조건은 `D>0`, `L>D/2`, `0<=t<D/2`입니다. 반구 endpoint L=D/2는 현재 반회전·boolean 생성 경로에서 지원하지 않아 입력 단계에서 거부합니다. 단위 변환·origin·두께가 좌표 정밀도에서 표현되지 않는 경우도 거부합니다. 입력에 과거 D/L/t 별칭을 추가하지 않으며 JSON 키는 위 이름을 사용합니다.

원호 → 180° 회전 → 복사·180° 회전 → sheet fragment 또는 solid fuse를 native OCC로 수행합니다. STEP 중간 파일을 생성하지 않습니다. 생성 보조 center/section은 model에 남기지 않고 origin 위치에서 직접 구성합니다. 열린 native ogive는 해석적인 바깥 방향을 sheet 기준으로 잡으며, solid는 CAD 안/밖을 검사합니다. t나 단위 등 설정이 바뀌면 재생성해야 합니다.

## 전역·국소 크기장

`mesh.target_size`와 `mesh.wave`가 있으면 적용 가능한 요청 길이의 최솟값을 사용합니다. wave는 균질·무손실 매질의 `c0 / f / sqrt(eps_r*mu_r) / elements_per_wavelength`를 출력 단위로 계산합니다. 둘 다 없으면 surface CAD bbox의 대각 길이 × `fallback_fraction`(기본 0.1)을 사용합니다. 자동 선택은 키를 생략해 표현하며 `target_size=0`은 허용하지 않습니다. 예를 들어 10 GHz·파장당 요청 10·진공 조건의 길이는 약 2.998 mm이므로, 5 mm cap과 함께 사용하면 약 2.998 mm를 적용합니다. 이 경우 fallback 비율을 바꿔도 적용 길이는 같습니다. 파장당 개수는 EM 정확도 보증이 아닙니다.

국소 자동 규칙은 기본으로 꺼져 있습니다. `examples/thin_plate.json`과 `examples/gaps.json`에서 각각 활성화한 예제를 제공합니다.

| 설정 | 목적과 적용 | 값을 바꿀 때 |
|---|---|---|
| `local.short_edges` | non-seam CAD edge의 실제 길이 / `divisions` | divisions를 키우면 해당 edge 목표가 작아짐 |
| `local.widths` | 볼록 평면 polygon의 실제 최소 지지선 폭 / `divisions` | 10×0.6 mm 판에서 3이면 0.2 mm 요청; 면적의 제곱근이나 축 방향 bbox 폭을 대신 쓰지 않음 |
| `local.gaps` | 분리 CAD의 bbox 후보를 실제 `occ.getDistance`로 확인하고 gap / `divisions`를 공간 Box에 적용 | 0.6/1.2 mm 간극에 3이면 각각 0.2/0.4 mm; 빈 공간의 체적 mesh 층 수가 아님 |
| `local.curves` | `[{"entity":1,"size":0.2}]`처럼 지정 curve 주변 보호 | 지정 size가 작아지면 해당 주변이 더 촘촘해짐 |
| `local.boxes` | `[{"bounds":[xmin,ymin,zmin,xmax,ymax,zmax],"size":0.2}]` | 지정 영역의 독립 목표를 적용 |
| `local.hold_distance` | 작은 목표를 유지할 거리; 생략하면 각 국소 목표 길이 | 전이 거리와 독립적으로 보호 범위를 넓히거나 줄임; 0 허용 |
| `local.transition_distance` | 유지 영역 밖의 전이 거리 | 생략 시 `(global-local)/growth_rate`; 기본 slope 0.3 |
| `local.sampling_fraction` | Distance의 geometry 표본 간격을 결정; 기본 0.25 | 줄이면 `Sampling` 증가, 근사 거리의 밀도 증가 |
| `mesh.minimum_size` | 명시적 최소 요청 길이 | 전역·필수 국소 요청보다 크면 `minimum_size_conflict`로 차단 |

예를 들어 전역 3 mm·국소 0.2 mm·유지 0.4 mm·slope 0.3이면 `DistMin=0.4`, 전이 거리 약 9.333, `DistMax≈9.733 mm`입니다. 전이 slope는 실제 인접 요소 크기비의 보증이 아닙니다. Box는 유지 거리만큼 영역을 확장하고 바깥에 `Thickness` 전이를 둡니다.

짧은 edge와 수동 curve에는 `Distance → Threshold`, 폭에는 해당 면/경계의 상수 `Restrict`와 경계 주변 전이, gap·수동 영역에는 `Box`를 적용하고 `Min`으로 결합합니다. `MeshSizeMin/Max`는 요청 field의 범위이며 모든 실제 edge 길이의 엄격한 상·하한이 아닙니다. 국소 목표의 전체 최솟값을 모든 특징의 값으로 복사하지 않습니다. 겹치는 영향 영역에서는 `Min`이 더 작은 요청을 적용합니다.

폭 자동 측정은 **직선 경계를 가진 단일 loop의 볼록 평면**을 지원합니다. hole·비볼록 neck·곡선 경계·곡면 폭은 요청 시 `width_unsupported`로 차단하며 필요한 면만 `widths.entities`로 선택하거나 수동 영역을 사용합니다. `short_edges.entities`는 curve tag, `gaps.pairs`는 surface tag 쌍입니다. 생략하면 지원 범위 전체를 검사합니다. 공유 연결/같은 solid 내부의 면을 분리 gap으로 취급하지 않고, 분리 entity의 접촉·거리 0·측정 실패도 정상 간극으로 처리하지 않습니다. gap Box는 최소 거리 주변의 보수적인 bbox 영역이며 임의 곡면 전체에서 같은 간극 폭을 의미하지 않습니다.

`local.max_sampling`(기본 4096), `max_pair_tests`(10000), `max_features`(4096)를 넘으면 요청을 느슨하게 바꾸지 않고 측정 미완료로 차단합니다. 폭 계산의 쌍 예산은 dense geometry 계산 전에 확인합니다. 이 한도는 CAD/field 측정의 한도이며 전체 실행의 자원 설정은 아래 `resources`와 구분합니다.

ONELAB에서는 `BRL/Sizing`의 cap·파장·하한과 `BRL/Local`의 자동 규칙·분할·유지·전이·sampling을 제어합니다. 고급 entity 선택·수동 curve/Box·측정 한도는 시작 JSON을 보존합니다. `BRL/03 Applied global size`는 실제 적용한 전역 요청을 출력 단위로 표시합니다. 예제 실행은 `run_gmsh_ui.bat examples/thin_plate.json` 또는 `examples/gaps.json`이며 Action 흐름은 같습니다.

발행 전 적용 field의 ID·type·계수·entity 목록·전역 크기 옵션을 확인합니다. 변경되면 재생성을 요구합니다. 개선의 비악화 판정에는 실제 edge 중점 길이 / CAD 거리 기반 국소 요청의 최대 비율을 추가했습니다. 이 감사는 Gmsh의 표본 Distance evaluator와 수치가 같다는 가정이나 모든 edge의 엄격한 목표 충족/EM 정확도 보증으로 쓰지 않습니다.

## 곡률·CAD 편차

`mesh.curvature`를 지정하면 국소 곡률로 초기 목표를 계산하고, 실제 CAD 표본 편차가 허용값을 초과한 CAD entity의 목표를 줄여 재생성합니다. 기본으로 꺼져 있으며, 새 예제 `cylinder.json`과 `circle_223.json`에서 활성화합니다.

```json
"curvature": {"absolute_tolerance": 0.02, "max_iterations": 3,
              "sampling_nodes": 10, "verification_nodes": 19}
```

| 설정 | 목적·적용·변경 효과 |
|---|---|
| `absolute_tolerance` | 출력 단위의 CAD 편차; 작게 하면 곡면/원호 목표가 대략 제곱근 비율로 작아짐 |
| `relative_tolerance` | 국소 CAD face의 `sqrt(area)`, curve의 arc length에 곱한 편차; 전체 bbox D를 사용하지 않음 |
| 두 tolerance 동시 지정 | 각 entity에서 더 엄격한 값을 사용; 둘 중 하나 이상 필요 |
| `max_iterations` | 최초 생성 이후 허용할 재생성 횟수, 기본 3·범위 0–10; 0도 편차 검사를 수행하고 초과 시 차단 |
| `sampling_nodes` | 생성 feedback의 edge당 표본 수, 기본 10; 삼각형당 55개 barycentric 표본 |
| `verification_nodes` | 최종 생성·개선·발행의 edge당 표본 수, 기본 19; 삼각형당 190개, sampling_nodes 이상 필요 |

예를 들어 R=10 mm·편차 0.001 mm인 원의 초기 분할 요구는 223입니다. 고정 200 clamp를 적용하지 않습니다. curve에는 `2*sqrt(2*R*delta-delta^2)`, surface에는 최대 절대 주곡률 반경을 이용한 `sqrt(6*R*delta)`를 초기 길이로 사용합니다. 평면의 곡률 요청은 전역 cap을 유지합니다. 작은 반경/특이점에는 유한 편차 해상도를 적용하고, 극점의 미정 주곡률은 인접 parameter에서 다시 구하며 실패하면 차단합니다. 이 초기식만으로 일반 곡면의 삼각형 내부 편차가 보장되지는 않습니다.

Gmsh `setSizeCallback`에서 기존 field 결과와 곡률 목표의 최솟값을 적용합니다. 원당 전역 `MeshSizeFromCurvature`는 0이며, seam도 곡률 경계 제어에 포함합니다. feedback은 초과한 face/curve별 배율과 해당 face의 경계 목표를 줄이므로 한 face 전체를 보수적으로 세분화할 수 있습니다. 형상/PID는 유지하되 재생성으로 node/element ID·연결은 바뀔 수 있습니다. node relocation 단계의 연결 보존·정확한 rollback 계약과 구분합니다.

현재 CAD를 유지한 채 원본 element ID별로 triangle 내부·edge와 CAD boundary line의 projection 거리를 측정하고, surface projection의 parameter round-trip과 trim 포함을 확인합니다. 구멍의 chord처럼 underlying surface 투영이 trim 밖이면 실제 face 경계 curve들에서 유효한 점을 찾아 거리를 측정하고 trim/round-trip을 다시 확인합니다. 평면에서는 trimmed closest distance이고 일반 곡면에서는 보수적인 유효 CAD 점까지의 거리이며 전역 최근접점 보증은 아닙니다. 후보를 검증할 수 없으면 차단합니다. `DiscretizationError`는 공식 소스 검토 후 원본 ID·projection 성공 계약 때문에 채택하지 않았습니다. 임시 편차 view나 파일은 만들지 않습니다. 설정한 최종 표본의 편차 검사를 개선 후보와 NAS 발행 직전 현재 mesh에서 다시 수행하고, 개선 수용 시 최대 편차 비율의 비악화도 요구합니다.

편차는 유한 표본의 mesh→CAD 거리입니다. 일반 CAD의 연속 최대 편차·양방향 Hausdorff 거리·EM 정확도를 보증하지 않습니다. 표본 수를 늘리면 측정값과 비용이 달라질 수 있습니다. `minimum_size`와 요구가 충돌하거나 반복/자원 한도에 도달하면 요청을 clamp해 성공 처리하지 않고 발행을 차단합니다.

## 실행 자원

최상위 `resources`는 생략해도 아래 기본값으로 동작합니다. ONELAB의 `BRL/Resources`에서도 같은 값을 설정합니다.

| 키 | 기본값 | 실제 검사 |
|---|---:|---|
| `max_nodes` | 150000 | 생성 후·검사/발행 시 현재 Gmsh model의 전체 node 수 |
| `max_triangles` | 200000 | 생성 후·검사/발행 시 현재 model의 1차 triangle 수 |
| `max_memory_mb` | 2048 | 현재 실행 프로세스의 private committed memory, MiB·Windows 검증 |
| `max_seconds` | 300 | 한 CLI 실행 또는 ONELAB Action의 작업 시간, UI idle 제외 |
| `max_projection_samples` | 20000000 | 곡률 편차 projection 표본 누계; 재생성·개선·발행이 같은 예산 소비 |

시간·메모리는 **협력적 검사**입니다. CAD/크기장/mesh API 호출 전후와 곡률 callback/표본 batch에서 확인하며, 단일 OCC/Gmsh native 호출을 강제 중단하거나 allocator를 제한하지 않습니다. 따라서 native 호출 중의 일시적 초과·peak memory·엄격한 wall-clock 종료를 보장하지 않습니다. 한도를 관측하면 이번 NAS 발행을 막고, 임시 NAS만 정리하며 이전 정상 결과는 보존합니다. 같은 ONELAB Action 내부 코어 호출은 예산을 공유하고, 다음 Action은 새 예산을 시작합니다.

ONELAB의 `BRL/Curvature`에서 활성화·절대/상대 편차·재생성 횟수·두 표본 수를 조정합니다. 이 설정 또는 자원 설정을 바꾸면 이전 scene은 재생성이 필요합니다. `Generate + publish NAS`의 기존 Action 흐름은 같습니다.

## 로컬 단계별 작업

각 단계는 `codex/rebuild-core`에서 로컬 파일 작성·검증·commit으로 진행합니다. 전체 구현·통합 검증 뒤 최종 GitHub PR을 준비하고, merge는 사용자 지시가 있을 때 수행합니다. 병합 성공을 확인한 뒤 해당 작업 branch를 로컬·원격에서 정리합니다.

## 테스트

```powershell
New-Item -ItemType Directory -Path .cache\tests -Force | Out-Null
New-Item -ItemType Directory -Force .cache\tests | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage6
```

Windows Gmsh DLL과 pytest의 기본 native FD capture 충돌을 피하도록 `--capture=sys`를 프로젝트 설정에 포함했습니다. 제품의 보고서·진단 파일 생성과 개발 테스트 기록은 구분합니다.

## 개발 원칙

새 구조에서 실행 흐름·설정·검사 반환값을 설계합니다. 기존 BRL의 런타임 모듈·가상환경을 참조하지 않습니다. 기존 코드는 검증할 동작과 재사용 후보를 확인하는 읽기 전용 자료로 취급합니다.

제품에는 웹 UI·서버·NAS viewer·조건 조합별 비교 생성·점수·등급·HTML/JSON 보고서·독립 진단 화면을 포함하지 않습니다. 생성·개선·정상 NAS 발행에 필요한 검사와 오류 설명은 유지합니다.

`AnalyseMeshQuality`에서 ICN만 계산하여 유효한 결과 확인과 개선 후보의 수용 판단에 사용합니다. 연결/topology와 CAD/기준 방향 법선은 별도 검사합니다. 임시 view는 ID별 결과를 읽은 뒤 성공·실패 모두에서 정리하고 표시 상태를 보존합니다. 메쉬 변경 후 재계산하며 이전 snapshot으로 새 결과를 판정하거나 발행하지 않습니다.

2단계의 104개 삼각형 비교에서 기존 판정과 ICN 값의 수용/거부 범위가 겹쳤습니다. 따라서 AR ≤ 3·최소각 ≥ 20°는 기존 발행 기준으로 유지하고 ICN 임계값으로 임의 변환하지 않습니다. IGE·Jacobian measure를 추가로 켜거나 점수 구조를 복원하지 않습니다. 개선은 위반 감소 또는 최소 ICN 상승과 함께 기존 형상·기하·크기·gradation 조건의 비악화를 요구합니다. 연결·분류가 유지된 후보만 정확한 좌표/parameter rollback을 허용하며, 구조 변경이나 복구 실패 시 발행을 차단합니다. 현재 검사 통과는 EM 정확도 보증이 아닙니다.
