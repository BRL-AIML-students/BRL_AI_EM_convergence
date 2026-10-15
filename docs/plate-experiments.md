# 평판 반복 생성과 A/B 비교

2026-10-15, main `3eb636c1be9c2c59103d8f67267686f80ed01659`의 실제 Gmsh ONELAB UI와 생성·검사·발행 흐름을 확인하고 확장했다. 별도로 존재하는 `mesh_ui.server` 웹 UI와 4사례 파장/크기 비교는 그대로 사용할 수 있다. 이번 A/B 기능은 `geometry_mesh.native_ui`의 기존 창에서 실행한다.

## 첫 실행: A 생성 → 같은 조건 B 생성 → 비교

1. 저장소 루트에서 `01_mesh_generator\run_plate_experiment.bat`을 실행한다. 기존 `run_gmsh_ui.bat`으로 시작했다면 왼쪽 `BRL → Action`에서 **6 - Plate practice preset**을 선택한다.
2. `BRL → Experiment`의 **Plate dimensions**, **Target length**, **Seed and algorithm**을 확인한다. 초기 실습값은 **40×30 mm, 목표 길이 3 mm, 알고리즘 6, 시드 1**이다. 교수님이 지정한 치수가 아니며 변경할 수 있다. 형상 치수는 입력 단위, 메쉬 크기는 출력 단위를 사용한다.
3. **1 - Generate and save**를 선택한다. 선택 후 자동 실행되어 Action이 Idle로 돌아온다. 별도의 Run 버튼을 누를 필요는 없다. 생성된 메쉬가 오른쪽에 표시되고 새 폴더로 저장된다. 첫 결과가 **Experiment → Run A**에 지정된다.
4. **7 - Repeat A as new B**를 선택한다. 저장된 A의 전체 설정과 시드를 다시 읽고 새로 생성하여 **Run B**에 지정한다. 현재 화면의 미저장 편집값은 A의 설정으로 교체된다. A의 파일은 유지된다.
5. **8 - Compare A and B**를 선택한다. 기본 브라우저에 저장된 `comparison.html`이 열린다. 브라우저 자동 열기가 동작하지 않으면 **Experiment → Comparison HTML**에 표시된 파일을 직접 연다.
6. 보고서 상단에서 **메쉬 / 노드 집합 / 연결 관계** 판정, 좌표 단위와 허용오차, 개수 차이를 확인한다. 아래에는 같은 시점·배율의 A/B와 겹쳐 보기, 실제 변 길이·품질 분포, 입력/적용값 차이가 있다. 휠 확대·축소, 드래그 이동, Yaw/Pitch와 초기화는 세 화면에 함께 적용된다.

창이 좁으면 메뉴 트리와 메쉬 화면 사이 경계를 드래그해 패널 폭을 조절한다. 긴 파일 경로·JSON 필드는 클릭하고 좌우로 이동해 확인할 수 있으며, 비교 HTML에는 전체 내용이 표시된다.

## 목표 길이 하나만 바꾸기

1. 기준 실행을 **Experiment → Run A**에서 선택한다.
2. **10 - Load A settings for one-change test**를 선택한다.
3. `BRL → Mesh → Fixed size (0 auto)`만 **3 → 5**로 바꾼다. 길이와 폭, 입력/출력 단위, 알고리즘과 시드는 유지한다.
4. **1 - Generate and save**로 새 B를 저장한다. **8 - Compare A and B**에서 변경 입력이 `mesh.target_size` 하나인지 확인한다.

시드 실험은 동일한 절차에서 **Mesh → Random seed**만 바꾼다. 보고서가 이를 `seed_change`로 구분한다. 같은 시드 반복은 `same_inputs_repeat`이다. 시드를 바꾸거나 프로그램을 재시작해도 메쉬가 달라진다고 보장하지 않는다. 이번 기능은 노드 좌표를 임의로 흔들지 않는다.

자동 크기 실험에서는 Fixed size를 0으로 바꾸고 Scale fraction을 지정한다. **Minimum size**는 수동 하한, **Automatic minimum**은 일반 모드에서 모델 크기 비율을 사용하는 선택이다. Controlled 자동 모드는 Minimum fraction으로 하한을 계산한다. 실제 적용 여부는 보고서 `sizing`의 값으로 확인한다.

다른 저장 결과를 비교하려면 **Output → Folder**를 해당 결과들의 부모 폴더로 지정하고 **9 - Refresh saved runs**를 선택한 뒤 Run A/B를 고른다. 선택 항목은 폴더의 절대 경로다. **Saved runs**는 유효·경고·생성 실패·파일 손상 등을 함께 나열하고, A/B 선택에는 비교 가능한 실행만 표시한다. 프로그램을 종료해도 실행 결과는 남는다.

## 실행별 보존 내용과 상태

생성(Action 1/7)과 기존 발행(Action 4)은 매번 시간·UUID가 있는 새 폴더를 원자적으로 발행한다. 기존 결과를 덮어쓰지 않는다.

| 파일/필드 | 내용 |
|---|---|
| `diagnostic.msh` | 생성한 Gmsh 메쉬. 모양 품질 기준에 미달해도 보존 |
| `mesh_snapshot.npz` | 실제 사용한 노드·좌표·삼각형 연결. pickle 없이 저장/읽기 |
| `report.json` | 형상·원점·단위·입력 설정, BRL 기본값, 적용값, Gmsh 기본값, 크기 결정 근거, 품질·개수·시간, 버전·스레드·시드·코드 상태와 소스 SHA-256 |
| `quality_report.html`, `gmsh.log` | 기존 상세 검사 보고서와 Gmsh 로그 |
| `*.nas` | 기존 품질/무결성 게이트를 통과한 경우에 발행 |
| `comparison.json`, `comparison.html` | 별도의 `ab_...` 폴더에 저장하는 수치·시각 비교 |

`report.json → experiment.mesh_state`가 연구 비교용 상태다.

| 상태 | 의미와 비교 처리 |
|---|---|
| `valid` | 기존 검사 통과, A/B 비교 가능 |
| `quality_warning` | 구조 검사는 통과했지만 AR/최소각 기준 미달. MSH와 스냅샷을 보존하고 비교 가능 |
| `invalid_mesh` | 퇴화 요소·비정합/법선 등 구조 게이트 또는 검사 보류. 진단 자료를 보존하되 동일성 비교 제외 |
| `generation_failed` | 생성 실행이 예외로 중단됨. 별도 `failed_.../report.json`에 입력·실패 이유·가능한 적용값을 보존 |
| `corrupt_file` | 목록을 읽을 때 JSON/아티팩트의 손상·누락 또는 SHA-256 불일치 확인. 비교 제외 |
| `legacy_no_snapshot` | 이전 형식 실행으로 스냅샷이 없음. 자동으로 단위/설정을 추정하지 않음 |

기존 `status=invalid` 및 NAS 발행 차단 정책은 유지한다. 따라서 모양 경고 실행은 기존 status가 invalid여도 `experiment.mesh_state=quality_warning`으로 비교할 수 있다. NAS 발행 여부를 메쉬 파일 존재 여부로 해석하면 안 된다. 이전 메쉬는 native File/Open으로 열고 검사·Action 4 발행을 통해 현재 모델의 스냅샷을 만들 수 있지만, 원래 생성 설정이나 분석적 형상 참조를 복원했다고 표시하지 않는다.

## 동일성 판정과 해석

좌표를 선택한 공통 단위로 환산하고 **절대 Euclidean 거리 ≤ 허용오차**를 사용한다. 기본값은 **1e-8 mm**이다. 공간 셀은 후보 탐색에만 쓰며 좌표 반올림 해시로 동일성을 결정하지 않는다. 두 방향 모두 후보가 하나뿐인 노드만 유일한 대응으로 인정한다.

- 모든 노드가 유일하게 대응하고 삼각형 연결이 같으면 동일하다. 파일 이름·노드/요소 ID·행 순서·삼각형 꼭짓점 순서는 무관하다.
- 노드 집합과 연결 관계를 별도로 판정한다. 같은 노드 집합에서 대각선만 바뀐 경우 연결 관계만 다르다고 표시한다.
- 대응 후보가 여러 개면 판정을 보류하고 해당 노드·변을 주황색으로 표시한다. 허용오차를 지나치게 크게 지정하면 모호해질 수 있다. 후보 탐색이 500만 회를 넘으면 허용오차 조정 안내와 함께 중단한다.
- 상대 집합에 없는 노드는 집합 차이다. 다른 메쉬의 노드를 강제로 일대일 대응하거나 이동량으로 해석하지 않는다. 공통으로 확인되지 않은 삼각형도 별도로 집계한다.
- 평행이동·회전 정렬을 하지 않는다. 전역 법선 방향/일관성은 기존 품질 감사에서 별도 확인한다. 비교 연결은 방향 없는 꼭짓점 관계다.

시각화에서 공통 부분은 회색, A에만 확인된 부분은 적색, B는 청색, 대응 불명확 부분은 주황색이다. **모양 기준 미달 면 (노란색)**을 켜면 실행별 품질 위반 삼각형을 강조한다. 수치 비교 결과가 화면과 함께 표시되며, 화면을 보고 동일성을 결정하지 않는다.

## 품질 지표

| 지표 | 정의 | 좋은 방향 |
|---|---|---|
| 실제 변 길이 | 공유 변을 중복 제거한 3D Euclidean 길이 | 목표와 분포를 비교. 작다고 항상 좋은 것은 아님 |
| Mean ratio | `4√3 A / (a²+b²+c²)` | 0~1, 1에 가까울수록 정삼각형 |
| Aspect ratio | `Lmax × perimeter / (4√3 A)` | 1 이상, 1에 가까울수록 좋음 |
| 최소 내각 | 삼각형 세 내각의 최소값, 도 | 0~60°, 클수록 좋음 |
| Gmsh minSICN | `gmsh.model.mesh.getElementQualities(elementTags, "minSICN")`, sampled minimum signed inverse condition number | 이상적 요소 1, 클수록 좋음. 전역 법선 감사와 구분 |

기존 `quality.analyze()`의 검증된 AR·각도·Mean ratio 및 구조 검사와 [Gmsh 공식 getElementQualities](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002fmesh_002fgetElementQualities)를 함께 사용한다. minSICN 호출이 지원되지 않거나 실패하면 미평가 사유를 기록하며 다른 지표로 몰래 대체하지 않는다. 길이·품질 모두 최소/분위수/평균/표준편차와 공통 구간 히스토그램을 제공한다. 히스토그램 세로축은 실행별 상대 빈도다. 이 값들은 메쉬 모양 지표이며 MoM·RCS 정확도나 AI 성능을 평가하지 않는다.

## BRL 기본값·Gmsh 기본값·실제 코드 위치

BRL의 일반 시작값은 **100×100 mm, auto, scale_fraction=.06, minimum_size_fraction=.0005, local/improvement 활성**이다. 새 **실습 프리셋**만 40×30 mm, fixed 3 mm, minimum .1 mm, Controlled, 알고리즘 6·시드 1, local/improvement 비활성으로 시작한다. Controlled 모드는 개선을 포함한 제외 제어를 `excluded_controls`에 기록한다. 입력 설정에 값이 남아 있더라도 적용값과 혼동하지 않는다.

| 설정 | BRL에서의 선택 | Gmsh 4.15.2 초기 기본값 |
|---|---|---|
| Algorithm | 일반: 국소 필드 적용 시 5, 그 외 6. Controlled: 6. `mesh.algorithm=5/6`으로 명시 변경 가능 | 6 |
| MeshSizeMin / Max | `sizing.plan()` 결과 | 0 / 1e22 |
| Curvature | 일반: chord 비율에서 원당 샘플 수 계산, Controlled: 0 | 0 |
| Smoothing | 일반 3, Controlled 1 | 1 |
| MaxNumThreads1D/2D/3D | 각각 1로 고정 | 각각 0 |
| RandomSeed | `mesh.random_seed`, 기본 1을 명시 적용 | 1 |
| RandomFactor / RandomFactor3D | Gmsh 값을 사용하고 실제 값 기록 | 1e-9 / 1e-12 |
| AR·최소각 기준 | BRL 기준 3 / 20° | BRL의 검사 게이트로, Gmsh 기본 게이트가 아님 |

Gmsh 기본값은 옵션 파일을 읽지 않는 초기화 직후 API로 읽어 `sizing.gmsh_defaults`에 기록한다. 이후 생성 직전 조회한 값은 `sizing.applied_options`다. [Gmsh 공식 옵션 문서](https://gmsh.info/doc/texinfo/gmsh.html#Mesh-options)와 함께 확인한다. 버전이나 플랫폼이 달라지면 실행 보고서의 실제 조회값을 우선한다.

| 위치 | 담당 |
|---|---|
| `geometry_mesh/config.py: DEFAULTS, validate()` | BRL 기본값·범위, 알고리즘/시드 검증 |
| `geometry_mesh/experiments.py: plate_preset()` | 변경 가능한 실습 프리셋 |
| `geometry_mesh/geometry.py: build()` | 입력→출력 단위 변환, OCC 형상·모델 크기 |
| `geometry_mesh/sizing.py: _controlled_plan(), plan(), apply()` | 자동·수동 크기 근거, 후보·하한·파장·예산·국소 필드, Gmsh 옵션 적용 |
| `geometry_mesh/session.py: prepare(), generate(), improve()` | 공통 생성·개선 흐름, 알고리즘/시드 및 실제 옵션 기록 |
| `geometry_mesh/quality.py: analyze()` | 기존 모양·크기·위상·법선 검사 |
| `geometry_mesh/pipeline.py: initialize(), publish_current()` | Gmsh 기본값 조회, 실행별 원자적 MSH/NAS·보고서 발행 |
| `geometry_mesh/experiments.py: preserve_snapshot(), compare_meshes(), compare_runs()` | 공식 품질 호출, 스냅샷 보존, 단위·공차·연결 비교 |
| `geometry_mesh/native_ui.py: parameters(), Controller` | 실제 ONELAB 입력/액션 연결 |
| `geometry_mesh/experiment_report.html` | 동기화된 시각 비교와 수치·분포 표시 |

Controlled auto에서는 bbox 대각선 `D`에 대해 `hMax=D×scale_fraction`, `hMin=D×minimum_size_fraction`이다. 파장을 켜면 `λ/N`과 각각 비교해 더 작은 값을 사용한다. 일반 auto/fixed는 작은 특징·간격·국소 필드 사용 여부·하한·사용자 cap·파장·예산 정책의 영향을 받는다. `candidate_rules`, `minimum_size`, `target_size`, `local.fields_applied`, `budget_conflict`, `wave`, `excluded_controls`가 최종 판단 근거다. Gmsh는 점·곡률·필드 등 크기 조건과 알고리즘을 결합하므로 최종 목표 길이도 실제 모든 변 길이의 상한을 보장하지 않는다.

## 실제 검증 결과

Windows x64, Python 3.12.10, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1에서 확인했다. 모두 40×30 mm 평판이며, 출력/비교 단위는 mm, 공차는 1e-8 mm다.

| 사례 | 노드 | 삼각형 | 실제 고유 변 길이 중앙값 | A와의 결과 |
|---|---:|---:|---:|---|
| A: h=3, seed=1 | 197 | 344 | 2.910231 mm | 기준 |
| B: 동일 입력 재생성 | 197 | 344 | 2.910231 mm | 노드·연결 모두 일치 |
| C: h=5만 변경 | 76 | 122 | 4.980888 mm | 노드 집합·연결 다름 |
| D: seed=2만 변경 | 197 | 344 | 2.910231 mm | 이번 평판에서는 일치 |
| E: AR 기준을 1.01로 강화 | 197 | 344 | 2.910231 mm | quality_warning으로 보존·비교 가능, 메쉬는 A와 일치 |
| F: Controlled auto, fraction=.08 | 117 | 196 | 3.888540 mm | hMax≈4 mm. 후보/하한 근거 보존 |

A의 실제 최소/최대 변은 2.105123 / 3.405427 mm다. C는 3.400648 / 5.765759 mm다. 입력 h=3 또는 h=5를 실제 변 길이라고 표시하지 않는다. E는 **경고 보존 경로를 검증하기 위한 엄격한 임계값 사례**이며, 심하게 불량한 삼각형을 인위적으로 만들었다는 뜻이 아니다.

`test_plate_experiments.py`는 실제 MSH 파일을 작성한 뒤 노드 ID·요소 ID·노드/요소 행 순서를 바꾸고 다시 읽어 **동일** 판정을 검증한다. 동일 노드의 다른 대각선, 단위 환산, 셀 경계를 가로지르는 공차, 모호한 대응, 손상된 배열/파일, 생성 실패 보존, ONELAB A→B→비교·한 변수 변경·기존 NAS 발행도 확인한다. 전체 Python 회귀 **188개 통과**. 기존 웹 UI의 생성·저장·4사례 비교와 CAD/단위/NAS 검사도 포함한다.

실제 Windows Gmsh 창에서 Action 1→7→8과 메쉬 표시·실행별 저장을 확인했다. 브라우저 비교 화면에서 나란히/겹쳐 보기, 휠 확대·축소, 드래그 이동의 동기화, 시점 초기화·노드 표시와 수치 결과를 확인했다. 브라우저 콘솔 오류가 없었다.

검증 자료를 새 폴더로 다시 생성하는 명령:

```powershell
# 01_mesh_generator 폴더에서 실행
..\.venv\Scripts\python.exe -m geometry_mesh.experiment_demo
# outputs/plate_evidence_.../index.html, evidence.json 및 실행·비교 폴더 생성

# 저장된 두 실행을 UI 없이 비교
..\.venv\Scripts\python.exe -m geometry_mesh.experiments "A 실행 폴더" "B 실행 폴더" --unit mm --tolerance 1e-8

# 저장소 루트에서 전체 회귀 검사
.\.venv\Scripts\python.exe -m pytest --basetemp .cache\pytest-local --tb=short
```

자동 검사에서 Windows sandbox의 loopback 제한과 임시 폴더 접근 제한이 발생할 수 있으므로, 일반 사용자 권한과 프로젝트 내부 임시 폴더로 검증했다. 새 checkout에서 `.cache`가 없다면 먼저 생성한다. 동일 머신의 로컬 결과이며 다른 OS/CPU/Gmsh 버전의 결정성, 대형 메쉬의 성능, 임의 CAD의 모든 교차/기하 오차를 검증하지 않았다. MoM·RCS 계산과 AI 학습은 구현하지 않았다.
