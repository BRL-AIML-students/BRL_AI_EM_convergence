# 메시 인터페이스

이 문서는 `01_mesh_generator`의 CLI·Python 세션·Gmsh 기본 UI, NAS 내보내기, 품질 보고서와 브라우저 뷰어의 입력 범위를 설명합니다.

## JSON 설정과 실행

CLI는 버전 1 JSON 설정 하나를 받습니다. CAD 경로는 설정 파일이 있는 폴더 기준으로 해석합니다. 출력 폴더는 프로세스의 현재 작업 폴더 기준입니다. 형상은 `plate`, `disk`, `sphere`, `box`, `cylinder`, `ogive`, `cad`, `fuse`, `cut`, `intersect`를 지원합니다. 길이 단위는 `m`, `cm`, `mm`, `um`입니다.

BREP 단위 변환은 솔리드와 함께 저장된 독립 sheet·curve·point에도 적용합니다. 상위 entity의 boundary는 중복 변환하지 않습니다. STEP/IGES는 파일의 단위 메타데이터에 따라 출력 단위로 변환합니다.

프로젝트 루트에서:

```powershell
cd .\01_mesh_generator
..\.venv\Scripts\python.exe -m geometry_mesh.cli examples\plate_wave_local.json
```

현재 위치가 `01_mesh_generator`인 경우:

```powershell
..\.venv\Scripts\python.exe -m geometry_mesh.cli examples\plate_wave_local.json --quiet
```

성공하면 표준 출력에 `status`와 `output_directory`를 담은 JSON 한 줄을 씁니다. 기본 실행은 진행 정보를 표준 오류에 표시하며, `--quiet`는 진행 정보만 생략합니다. 종료 코드는 다음과 같습니다.

| 코드 | 의미 |
|---|---|
| 0 | 메시 생성, 품질 게이트 및 NAS 검증을 완료 |
| 1 | 설정, CAD, 메시 생성 또는 실행 중 예외 |
| 2 | 실행은 끝났지만 품질 게이트로 `invalid`; 정상 NAS 발행 없음 |

출력은 고유한 실행 하위 폴더에 원자적으로 발행됩니다. 정상 완료 시 설정 이름의 `.nas`, `diagnostic.msh`, `report.json`, `quality_report.html`, `gmsh.log`가 포함됩니다. 필수 게이트가 있으면 `status: invalid`이고 진단 파일만 발행합니다. NAS 독립 검증에 실패하면 NAS를 제거합니다. 비유한 진단 수치는 JSON/HTML에서 null로 기록합니다.

## NAS 데이터 형식

CAD volume 경계의 법선은 현재 삼각형과 CAD의 외향 방향을 발행 직전에 비교합니다. 방향이 뒤집히거나 판정이 모호하면 NAS를 발행하지 않습니다. cavity의 내벽도 솔리드 밖을 향하는 방향을 기준으로 검사하며 메시를 자동으로 뒤집지 않습니다. `topology_and_normals.metrics.outward_normals`에 검사 범위와 문제 요소를 기록합니다. CAD solid 정보가 없는 native mesh와 열린 sheet의 절대 방향은 `not_assessed` 범위이며 인접 winding 검사는 계속 수행합니다.

생성기는 ASCII 자유 필드(punch) NAS 파일을 씁니다. 데이터 카드는 `GRID`, `CTRIA3`, 마지막의 단일 `ENDDATA`입니다. 주석에는 `$ length unit: <단위>`가 있습니다.

- `GRID`: 양의 정수 노드 ID와 X/Y/Z 좌표. 좌표는 `output_unit`으로 기록됩니다.
- `CTRIA3`: 요소 ID, PID, 세 개 노드 ID. 삼각형은 1차 표면 요소입니다.
- 노드 ID와 요소 ID는 메시의 Gmsh ID를 보존합니다. 연결 목록의 노드 순서는 요소 방향을 보존합니다.
- PID는 정렬된 각 기하 표면에 하나씩 배정되며, 시작값은 `export.pid_start`(기본 1)입니다. `report.json`의 `surface_groups`에 PID, 이름, Gmsh 표면 태그가 기록됩니다. PID는 재료 속성이나 물성 정의가 아닙니다.
- 생성 후 내보낸 좌표, ID, 연결, PID를 다시 비교하고 pyNastran으로 독립 파싱합니다. 결과는 `assessment.scores.nas_export_integrity`와 NAS 검증 정보를 통해 확인할 수 있습니다.

현재 브라우저 뷰어는 자유 필드와 고정 폭 표면 데이터의 `GRID`, `GRID*`(이어쓰기 줄 포함), `CTRIA3`, `ENDDATA`를 읽습니다. 셸 두께, 물성 카드, 2차 요소와 체적 요소는 뷰어의 표면 메시 입력 범위가 아닙니다. 대형 메시의 표시 속도는 브라우저 성능에 따라 달라집니다.

## 품질 보고서

`report.json`은 기계 판독용 보고서이며, `quality_report.html`은 같은 정보를 사람이 읽기 쉽게 표시합니다. 주요 필드는 다음과 같습니다.

- `report_version`, `run_id`, `created_utc`, `status`: 보고서 버전과 실행 식별자 및 전체 상태.
- `configuration`, `units`, `geometry`, `sizing`: 사용 설정, 길이 단위 변환, 형상 메타데이터, 메시 크기 계획 및 사후 측정값.
- `surface_groups`: PID와 기하 표면의 대응.
- `assessment.fatal_gates`: 정상 NAS 발행을 막는 형상·구조·검토 필요 오류 목록.
- `assessment.scores`: `element_shape`, `size_compliance`, `gradation_and_features`, `geometry_fidelity`, `topology_and_normals`, `nas_export_integrity`에 대한 점수, 측정치, 문제 요소 ID와 평가 범위.
- `score_profile`: 점수 기준의 버전이 지정된 프로필.
- `improvement_history`: 시도한 최적화 방법·채택 여부·전후 형상 지표. 실행별 기록입니다.
- `artifacts`, `environment`, `limitations`: 결과 파일, 실행 환경, 적용 한계.

점수는 프로필의 기준에 따른 형상 및 구조 지표입니다. 해석기 수렴이나 산란 오차를 직접 검증하지 않습니다. `not_assessed`인 항목은 검증 근거가 없음을 나타냅니다. 파장 기반 크기 규칙과 요소 크기 목표 또한 해석 정확도를 보증하지 않으므로, 실제 문제에 맞춘 수렴 검사가 필요합니다. CAD/CSG 가져오기 형상 충실도와 좁은 간격 검출은 보고서의 한계를 함께 확인하세요.

## 브라우저 UI

통합 UI는 `plate`, `disk`, `sphere`, `box`, `cylinder` 및 STEP/STP/IGES/IGS/BREP 형상을 받습니다. UI에서 CAD 경로를 직접 입력하거나 파일을 업로드할 수 있습니다. 업로드 제한은 50 MiB이며, 업로드 파일은 서버 임시 작업 폴더에 저장됩니다. 결과 폴더를 상대 경로로 지정하면 `01_mesh_generator` 기준으로 해석합니다. 입력 단위와 NAS 출력 단위를 선택하고 파장 목표, 재료의 상대 유전율·투자율, 자동 국소 세분화 또는 국소 상자 설정을 입력합니다. 메시 생성이 끝나면 NAS 결과를 오른쪽 뷰어에 표시하고, 실행 상태와 출력 폴더를 보여줍니다. JSON/HTML 보고서는 출력 폴더에 저장됩니다. UI는 보고서의 개별 점수표를 표시하지 않습니다. 생성 오류는 상태 표시와 세부 정보에 표시됩니다.

서버는 `127.0.0.1`에만 바인딩하고 기본 브라우저를 실행합니다. 포트 기본값 0은 사용 가능한 포트를 자동 선택합니다. 종료 버튼 또는 Ctrl+C로 서버를 닫을 수 있습니다. 로컬 HTTP API는 UI 세션 토큰 헤더를 요구합니다.

| 경로 | 메서드 | 역할 |
|---|---|---|
| `/api/upload-cad?name=<파일명>` | POST | CAD 파일을 임시 폴더에 업로드 |
| `/api/jobs` | POST | JSON 설정을 제출하고 비동기 메시 작업 생성 |
| `/api/jobs/<작업 ID>` | GET | 실행 상태, 오류, 보고서 메타데이터 조회 |
| `/api/results/<작업 ID>` | GET | 완료된 작업의 NAS 파일 읽기 |
| `/api/shutdown` | POST | 활성 생성 작업이 없을 때 서버 종료 |

없는 작업이나 아직 발행되지 않은 NAS 결과는 404, 인증 실패는 403, 설정 및 실행 요청 오류는 400으로 응답합니다. 서버 API와 CLI는 역할이 다릅니다. CLI 종료 코드 2는 품질 fatal gate가 발생했음을 뜻합니다. UI는 `invalid` 상태, fatal gate 세부 정보와 `report.json` 경로를 표시하며 그 작업의 NAS를 뷰어에 보내지 않습니다. 별도 수동 서버 실행은 다음과 같습니다.

```powershell
..\.venv\Scripts\python.exe -m mesh_ui.server --no-browser --port 8765
```

MoM 연결과 해석 교정은 사용자 요청 전까지 작업 범위에 포함하지 않습니다.

## 품질 게이트 v2

설정 `version: 1`의 기존 필드는 유지하며 선택적 `quality` 필드를 추가했습니다. 보고서와 프로필 버전은 2.0.0입니다. 기존 설정에도 새 기본 게이트가 적용됩니다. 모든 요소가 Verdict형 AR ≤ 3 및 최소 내각 ≥ 20°를 만족해야 정상 NAS가 발행됩니다. 숫자는 초기 기하 운영 정책이며 해석 정확도 보증값이 아닙니다. 자동 예외는 없습니다.

```json
{"quality": {"max_aspect_ratio": 3, "min_angle_deg": 20,
  "topology": {"boundary_mode": "auto", "absolute_tolerance": 0,
    "relative_tolerance": 1e-10, "protected_gap": null,
    "separated_surface_pairs": [], "max_candidate_tests": 2000000}}}
```

AR는 1–3, 최소 내각은 20–60° 범위에서 더 엄격하게 설정할 수 있습니다. `boundary_mode`는 `auto`, `open`, `closed`이며 auto는 CAD 체적의 표면 태그를 각 메시 연결 성분과 대조합니다. 열린 CAD의 경계 밖에 생긴 노출 모서리도 차단합니다. 공차의 절대값과 `protected_gap`은 출력 길이 단위입니다. 분리 의도는 Gmsh 표면 태그 쌍으로 명시하며 보고서의 `surface_groups`와 대조하세요. CAD 변경 후 태그를 다시 확인해야 합니다.

확인된 정점–모서리 T-junction, 공유되지 않은 일치 위치, 분리된 정점 fan은 차단합니다. 근접 후보가 모호하거나 탐색 예산이 소진되면 `quality_gate_status: review_required`이고 NAS를 발행하지 않습니다. 일반적인 삼각형 면 교차의 부재를 이 정점–모서리 검사로 보증하지 않으며 해당 범위는 `not_assessed`로 기록합니다.

출력 폴더에 `diagnostic.msh`를 보존하므로 invalid 결과도 Gmsh에서 조사할 수 있습니다. 정상 NAS만 `artifacts.nas`로 기록합니다. NAS 독립 검증에 실패하면 정상 파일을 제거합니다. `assessment.quality_gate_status`와 구조 오류를 반드시 확인하세요. CLI 종료 코드 0/1/2와 기존 UI 계약은 유지됩니다.

## 제한된 개선 설정

```json
{"mesh": {"improvement": {"enabled": true, "max_passes": 3,
  "methods": ["Relocate2D", "Laplace2D"], "fragment_surface_tags": []}}}
```

최대 횟수는 0–3이며 methods는 두 표면 최적화 방법의 비어 있지 않은 목록입니다. 형상 게이트 위반에만 자동 개선을 시도합니다. 원시 기하·크기·크기 증가 지표와 위상·PID를 다시 확인해 악화되면 좌표를 복원합니다. 개선 상한 뒤 위반이 남으면 NAS를 발행하지 않습니다.

`fragment_surface_tags`는 사용자가 연결할 열린 CAD 표면 태그를 두 개 이상 명시하는 생성 전 처리입니다. 원본–출력 대응과 PID를 보존합니다. 체적이 포함된 모델과 원본 PID가 모호한 겹침은 거부합니다. 임의 기존 메시의 T-junction 자동 분할·용접은 제공하지 않습니다.

## Gmsh 기본 UI

루트에서 설치 후 `01_mesh_generator\run_gmsh_ui.bat`을 실행합니다. JSON 설정을 인수로 줄 수도 있습니다. `01_mesh_generator`에서 직접 실행할 경우:

```powershell
..\.venv\Scripts\python.exe -m geometry_mesh.native_ui examples\plate_wave_local.json
```

Gmsh ONELAB의 BRL 트리에 형상 숫자·CAD 경로·단위·크기·품질 기준·개선·출력 설정이 나타납니다. `BRL/00 Action` 값을 바꾸면 실행한 뒤 0으로 돌아옵니다: 1 생성, 2 현재 메시 검사, 3 현재 메시 개선, 4 재검사 후 발행, 5 종료. Result에서 상태와 지표를, 후처리 뷰에서 AR 분포와 문제 위치를 확인하세요. 형상/단위/크기 설정 변경은 1로 재생성해야 합니다. CSG는 JSON CLI를 사용합니다.

Gmsh File/Open으로 연 CAD는 먼저 Mesh 2D를 실행하고 2/4로 검사·발행합니다. 기존 MSH도 불러올 수 있습니다. 이 경로는 현재 좌표를 변환하지 않고 출력 단위로 해석하며, BRL 입력 단위 변환을 하지 않습니다. 파일의 실제 단위를 확인하세요. 한 표면의 복수 물리 그룹은 모호한 PID로 거부합니다. 모델·메시·설정 변경 후 이전 판정은 무효화하며, 4는 항상 현재 메시를 다시 검사합니다. Gmsh 자체 File/Save는 BRL 품질 게이트를 거치지 않습니다.

## Python 실행·세션 API

독립 생성은 `geometry_mesh.pipeline.run(configuration)` 또는 `run_file(path)`을 사용합니다. run은 Gmsh 초기화/종료를 소유하므로 이미 열린 세션에서는 호출하지 않습니다. 세션을 유지하며 생성·검사·발행하려면 다음 경로를 사용합니다.

```python
import gmsh
from geometry_mesh.config import validate
from geometry_mesh.pipeline import initialize, publish_current, _profile
from geometry_mesh.session import prepare, generate, current, improve

initialize()
try:
    context = prepare(validate({"name": "plate"}))
    generate(context)
    mesh, assessment, history = improve(context, _profile())
    # current(context, _profile()) inspects the current mesh without export.
    report = publish_current(context, history)  # fresh inspection + gated output
finally:
    gmsh.logger.stop()
    gmsh.finalize()
```

File/Open 등 기존 모델은 `session.adopt_current(configuration)`으로 채택합니다. Gmsh 작업은 같은 main thread/세션에서 순차 실행합니다. `_profile`은 현재 내부 프로필 접근 함수이며 장기 안정 API로 보장하지 않습니다. 이 API는 메시의 독립 생성·확인용이고 MoM 연결·교정은 포함하지 않습니다.

## ogive 내부 형상

`geometry.kind="ogive"`와 `parameters`의 `D`, `L`, `t`를 입력합니다. `origin`은 선택 사항입니다. 입력 길이 단위를 따르며 축은 +Z입니다. 기존 tangent-ogive 원호·180° 회전/복사 방식으로 생성하고 STEP을 쓰지 않습니다. `t=0`은 밑면이 열린 곡면, `t>0`은 내면·외면·바닥 링을 가진 벽 두께 솔리드입니다. `D>0`, `L>=D/2`, `0<=t<D/2`를 요구하며 기존 두께 생성은 `L>D/2`에서 지원합니다. 메시 출력은 1차 삼각형 표면입니다. ogive의 해석적 mesh 형상 오차 평가는 아직 제공하지 않습니다.

## 자동 NAS 이름

`naming.automatic=true`는 형상명/원본명, 입력 치수·단위, 최종 `hMin`·`hMax`와 출력 단위, 주파수 `f`(GHz)·파장당 요소 수 `N`, 선택적 `naming.case`를 연결합니다. configID는 사용하지 않습니다. 소수점은 `p`로 표기하고 case는 마지막에 붙입니다. 기준 사례는 빈 case입니다. 외부 CAD는 `naming.source_name`에 원본 파일명을 지정할 수 있고 UI 업로드는 이를 보존합니다. 전체 설정은 report.json에 기록하고 반복 실행은 별도 run 폴더에 보관합니다. hMin/hMax는 Gmsh 제어값이며 실제 edge 길이의 보증 범위가 아닙니다. 기존 JSON에 name이 있고 naming이 없으면 수동 이름을 유지합니다.

## 파장·크기 비교 실험

브라우저 UI에서 `파장·크기만 비교하는 조건 사용`을 켜면 `mesh.controlled=true`로 실행합니다. 파장 ON/OFF와 최소·최대 크기 자동 계산 ON/OFF를 선택할 수 있습니다. 자동 계산은 bounding box 대각선 길이에 scale_fraction / minimum_size_fraction을 곱해 hMax / hMin을 정합니다. 자동 OFF는 출력 단위의 수동 hMin(minimum_size), hMax(target_size)를 사용합니다. 파장 ON은 균질·무손실 매질의 파장 / N으로 상한을 제한하며 hMin이 이보다 크면 함께 줄이고 이를 보고서에 기록합니다.

비교 조건은 Mesh.Algorithm=6, Mesh.Smoothing=1, 곡률 제어=0, point·boundary 크기 전달=1, 1차 삼각형으로 고정합니다. 작은 특징·국소/Box field·narrowGap·element budget·추가 Relocate2D/Laplace2D 개선을 적용하지 않습니다. 실제 applied_options, candidate_rules, 제외된 제어, 생성 시간, code_commit/code_dirty를 보고서에 기록합니다. 비교 조건 OFF는 기존 경로를 사용하므로 기능별 순수 비교로 해석하지 않습니다.

`4개 사례 일괄 생성`은 현재 형상·단위·주파수·재료를 유지해 baseline(수동/OFF), waveOnly(수동/ON), autoSizeOnly(자동/OFF), combined(자동/ON)을 생성합니다. combined의 파일명 suffix는 생략합니다. 자동 ON 상태에서도 수동 hMin/hMax가 baseline에 필요합니다. CLI는 다음과 같습니다(01_mesh_generator에서 실행).

```powershell
..\.venv\Scripts\python.exe -m geometry_mesh.cli examples\plate_comparison.json --compare
```

UI 서버는 POST /api/comparisons로 일괄 생성을 받고 GET /api/results/<job>?case=<case>로 선택한 정상 NAS를 반환합니다. 일반 생성은 기존 POST /api/jobs를 사용합니다. 일괄 폴더의 comparison.json에는 사례별 상태·경로·NAS·최종 크기·triangle 수·적용 옵션·시간·환경과 실패 원인이 저장됩니다. 품질 실패 시 해당 NAS는 발행하지 않고 diagnostic.msh와 보고서를 남기며 다른 사례는 계속 생성합니다. 일부 실패는 partial 상태와 CLI exit code 2로 표시합니다. 중단된 일괄 작업의 manifest는 running 상태와 완료 사례를 보존합니다.

파일명은 가독성을 위해 최대 8 유효 숫자로 표시하며 정확한 전체 수치는 report.json에 기록합니다. Gmsh에서 외부 모델을 직접 열어 채택한 경우 생성 크기 이력을 추정하지 않고 자동 이름에 native_current_model_hMinNA_hMaxNA를 표시합니다.

일괄 비교는 mesh 생성 검증이며 MoM 정확도 검증을 수행하지 않습니다. MoM 연결 전에 단위·PID·normal·열린 경계/재료·formulation·basis·입사 조건·solver tolerance를 확인해야 합니다. 비교 실험에서는 이 조건을 고정하고 기준해 또는 세분화 수렴 결과에 대해 관측량 오차·unknown 수·시간·메모리를 비교합니다. ogive의 입력 t는 재료 정보를 대신하지 않습니다.
