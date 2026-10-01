# 메시 인터페이스

이 문서는 `01_mesh_generator`의 `geometry_mesh` CLI, NAS 내보내기, 품질 보고서와 브라우저 뷰어의 입력 범위를 설명합니다.

## JSON 설정과 실행

CLI는 버전 1 JSON 설정 하나를 받습니다. CAD 경로는 설정 파일이 있는 폴더 기준으로 해석합니다. 출력 폴더는 프로세스의 현재 작업 폴더 기준입니다. 형상은 `plate`, `disk`, `sphere`, `box`, `cylinder`, `cad`, `fuse`, `cut`, `intersect`를 지원합니다. 길이 단위는 `m`, `cm`, `mm`, `um`입니다.

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
| 2 | 실행은 끝났지만 품질 게이트로 `invalid`; NAS는 없거나 독립 검증 실패로 사용할 수 없음 |

출력은 고유한 실행 하위 폴더에 원자적으로 발행됩니다. 정상 완료 시 설정 이름의 `.nas`, `report.json`, `quality_report.html`, `gmsh.log`가 포함됩니다. 치명적 품질 게이트가 있으면 보고서에는 `status: invalid`가 기록됩니다. 초기 메시 품질 게이트가 발생하면 NAS를 쓰지 않습니다. NAS 독립 검증 자체가 실패하면 검증 후 파일은 폴더에 남을 수 있으므로 사용하지 마세요.

## NAS 데이터 형식

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
- `assessment.fatal_gates`: 결과 발행을 막는 구조 오류 목록.
- `assessment.scores`: `element_shape`, `size_compliance`, `gradation_and_features`, `geometry_fidelity`, `topology_and_normals`, `nas_export_integrity`에 대한 점수, 측정치, 문제 요소 ID와 평가 범위.
- `score_profile`: 점수 기준의 버전이 지정된 프로필.
- `artifacts`, `environment`, `limitations`: 결과 파일, 실행 환경, 적용 한계.

점수는 프로필의 기준에 따른 형상 및 구조 지표입니다. 해석기 수렴이나 산란 오차를 직접 검증하지 않습니다. `not_assessed`인 항목은 검증 근거가 없음을 나타냅니다. 파장 기반 크기 규칙과 요소 크기 목표 또한 해석 정확도를 보증하지 않으므로, 실제 문제에 맞춘 수렴 검사가 필요합니다. CAD/CSG 가져오기 형상 충실도와 좁은 간격 검출은 보고서의 한계를 함께 확인하세요.

## 브라우저와 후속 MoM 연계

통합 UI는 `plate`, `disk`, `sphere`, `box`, `cylinder` 및 STEP/STP/IGES/IGS/BREP 형상을 받습니다. UI에서 CAD 경로를 직접 입력하거나 파일을 업로드할 수 있습니다. 업로드 제한은 50 MiB이며, 업로드 파일은 서버 임시 작업 폴더에 저장됩니다. 결과 폴더를 상대 경로로 지정하면 `01_mesh_generator` 기준으로 해석합니다. 입력 단위와 NAS 출력 단위를 선택하고 파장 목표, 재료의 상대 유전율·투자율, 자동 국소 세분화 또는 국소 상자 설정을 입력합니다. 메시 생성이 끝나면 NAS 결과를 오른쪽 뷰어에 표시하고, 실행 상태와 출력 폴더를 보여줍니다. JSON/HTML 보고서는 출력 폴더에 저장됩니다. UI는 보고서의 개별 점수표를 표시하지 않습니다. 생성 오류는 상태 표시와 세부 정보에 표시됩니다.

서버는 `127.0.0.1`에만 바인딩하고 기본 브라우저를 실행합니다. 포트 기본값 0은 사용 가능한 포트를 자동 선택합니다. 종료 버튼 또는 Ctrl+C로 서버를 닫을 수 있습니다. 로컬 HTTP API는 UI 세션 토큰 헤더를 요구합니다.

| 경로 | 메서드 | 역할 |
|---|---|---|
| `/api/upload-cad?name=<파일명>` | POST | CAD 파일을 임시 폴더에 업로드 |
| `/api/jobs` | POST | JSON 설정을 제출하고 비동기 메시 작업 생성 |
| `/api/jobs/<작업 ID>` | GET | 실행 상태, 오류, 보고서 메타데이터 조회 |
| `/api/results/<작업 ID>` | GET | 완료된 작업의 NAS 파일 읽기 |
| `/api/shutdown` | POST | 활성 생성 작업이 없을 때 서버 종료 |

없는 작업이나 아직 발행되지 않은 NAS 결과는 404, 인증 실패는 403, 설정 및 실행 요청 오류는 400으로 응답합니다. 서버 API와 CLI는 역할이 다릅니다. CLI 종료 코드 2는 품질 fatal gate가 발생했음을 뜻합니다. UI는 `invalid` 상태, fatal gate 세부 정보와 `report.json` 경로를 표시하며 그 작업의 NAS를 뷰어에 보내지 않습니다. NAS 파일이 폴더에 남아 있더라도 독립 검증 실패 결과는 사용하지 마세요. 별도 수동 서버 실행은 다음과 같습니다.

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
