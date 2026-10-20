# 개발 검증과 유지보수 기록

정리일: 2026-10-20. 사용 흐름·알고리즘·변수·발행 조건은 [사용자 guide](mesh-generator-guide-ko.html)를 기준으로 읽는다. 이 파일은 개발 증거와 이력 연결을 보존하며, 제품의 실행 보고서가 아니다.

## 현재 기준과 변경 범위

- 고정 환경: Python 3.12.14, uv 0.12.20, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1, pytest 8.4.2. `pyproject.toml`, `uv.lock`, `.python-version`으로 환경을 관리한다.
- Gmsh DLL SHA256: `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`. 이 build의 식별값이며 다른 build의 동일 결과 보증이 아니다.
- 문서 정리 전 source commit: `0e1f4daf2d5f5cf4253671499e517b83d4d1870f`.
- 문서 정리 전 게시 head: `bcf7ad0460d07c7dd01db297fe86136c7923b277`, tree `9964f2ab9ad2f78eb3965ec9d5a3594325968bd8`.
- 앞선 문서 정리 작업은 guide·README·개발 지침만 변경했다. 아래 통합 수치 시험은 당시 기존 실행의 기록이며 문서 작업 중 새로 수행한 결과가 아니다.

## 2026-10-20 generator 재검토 수정

수정 전 source `cdd74a1becd689db96b91a1edeaed4412268b3df`, 게시 main `20539bad4c21a390f8ea83613a015814b0449ad8`에서 시작했다. 상세 원인·수정 결정은 [재검토 계획 및 구현 기록](generator-reassessment-plan-ko.md)에 있다. 아래의 이전 통합 수치/hash와 구분한다.

- Ogive의 pole 유한 해상도를 중복 축소하던 곡률 feedback을 수정했다. 실제 편차 검증·minimum_size 충돌·AR/최소각·ICN·topology·법선·rollback·NAS 독립 대조는 유지한다.
- 동일 CAD·좌표·ID·연결·surface·1D 경계 요소의 검증된 편차만 재사용한다. 변경된 mesh의 편차 위반과 경계 선 요소 제거 시 재계산/차단 시험을 통과했다.
- Resources 모듈·ONELAB 항목·JSON schema와 국소 표본/특징/쌍/크기 감사 및 topology 작업량 중단 조건을 삭제했다. 표본/반복 입력의 고정 상한과 강제 단일-thread 설정도 제거했다. 사용자 지정 알고리즘 반복 횟수, 유효한 수치·CAD·품질 검사는 유지한다.
- Native 곡면의 Widths는 model 삭제 전에 거부한다. 곡면으로 전환하면 비활성 Curvature를 상대 .001로 켜며 이후 사용자가 직접 해제할 수 있다. UI 기본 ogive 전환 → Generate + publish NAS도 실제 생성·검사·발행을 통과했다.
- 생성 후 triangles·faces 표시와 bbox/viewport 맞춤을 적용한다. Idle은 무거운 CAD/mesh 재검사·카메라 재설정을 하지 않으며 Action/발행에서는 현재 상태를 검사한다. 잘못된 확대/이동 상태에서 cube→D50/L100 ogive→sphere→179° dihedral로 전환하는 실제 FLTK 렌더링을 확인했다. 독립 재읽기한 조밀한 ogive NAS도 전체 형상이 화면에 들어왔다.
- 성공 NAS 폴더명에 형상/치수를, 파일 주석에 geometry와 입력 단위를 넣었다. 실패 상태는 이번 실행의 NAS가 없음을 명시한다. 제품 sidecar는 추가하지 않았다.

| 검증 | 결과 |
|---|---|
| D50/L100/t0 mm, target 10, minimum .01, absolute .01, relative .001 | 33,375절점 / 66,536삼각형; 첫 24,916삼각형 q=1.33913 → 재생성 1회 후 q=.757532 |
| 독립 해석 ogive 거리, barycentric n=10/19/37 | .00755071 / .00757532 / .00759446 mm; 지정 .01 mm 이내 |
| 형상 품질 및 NAS | AR max 2.47228 / 최소각 23.9532°; 필수 검사·독립 좌표/ID/connectivity/PID 대조 통과 |
| 복잡한 fillet BREP, target .15 / absolute .01 | 초기 4,012삼각형 q=1.80625 → 4,256삼각형 q=.946149; 두 실행 NAS bytes 동일. 이전 4,236개에서의 변화는 새 feedback의 8개 face 재분할에 따른 것 |
| 동일 CAD/field의 Algorithm 5/6 대조 | 폭 제어 판은 둘 다 통과. D2/L3 ogive δ=.02에서 5는 최소각16.6604°·shape 위반2개, 6은26.4020°·위반0개. 현행6 유지 |
| Guide | 16 section·23 table·6 MathML·7 SVG. 태그 중첩·ID·목차/로컬 링크·inline XML 검증 통과 |

전체 회귀는 **332 passed in 442.04s**였다. 이후 추가한 기본 곡면 전환 발행·native thread 설정 보존 검사를 포함해 `tests/test_reassessment.py` **10 passed in 45.61s**를 다시 확인했다. 최종 수집 항목은 334개이며 추가 두 항목은 후속 10개 실행에 포함된다. 저장소 pytest 옵션(`--capture=sys`, `--import-mode=importlib`)을 유지했다. Runtime AST/compileall 및 `git diff --check`도 통과했다.

D50/L100 검증 명령은 `.\.venv\Scripts\python.exe -X utf8 -m tools.reassessment_acceptance`, 화면 맞춤은 `-m tools.reassessment_display`다. 최종 D50 실행은 349.69초였으며 다른 회귀 검사와 동시 실행한 관측값이다. 처리 시간 보증이 아니다. 기본 Gmsh 4.15.2 session의 General.NumThreads=1, Mesh.MaxNumThreads1D/2D/3D=0을 확인했으며 엔진이 별도 상한을 강제하지 않는다.

검증된 NAS 한 파일을 `outputs/run_ogive_diameter50_length100_thickness0_a1607459b3844a839b3c10464bb3bde0/mesh.nas`에 두고 검증 원본과 SHA256을 대조했다. 개발 증거와 실행 산출물은 Git에 포함하지 않는다.

## 2026-10-20 native UI 깜빡임 수정

- 대상: `brl_mesh/native_ui.py`, `tests/test_native_ui.py`, guide의 Idle 설명. Launcher·생성 알고리즘·검사/발행 기준은 변경하지 않았다.
- 원인: `wait(.2)` 다음에 매번 `fltk.update()`를 호출했다. Gmsh 4.15.2 source에서 이 API는 `updateViews(true, true)` → `onelabGroup::rebuildTree(true)`로 연결되며 트리/입력 위젯을 재구성한다. Idle도 Action 값을 다시 썼다.
- 수정: Idle Action은 쓰기 없이 반환한다. 표시 조건·상태·Action 소비에 따른 변경을 모아 해당 cycle에서만 UI를 갱신한다. 같은 상태/경로/적용 크기는 다시 쓰지 않는다. `wait(.2)`의 이벤트 처리, 현재 CAD/field/mesh 무효화 검사, 닫힌 창 보호는 유지한다.
- 새 검증: 고정 `.venv`에서 `tests/test_native_ui.py` **23 passed in 2.89s**. Idle, 표시 조건 전환, 지속되는 잘못된 설정, 잘못된 Action, NAS 발행 뒤 대기에서 불필요한 갱신/값 쓰기가 없음을 확인했다. 기존 변경 무효화·CLI/NAS 일치·오류 소비·창 종료 시험도 통과했다.
- 실제 FLTK 검증: 10 event-loop cycle 중 cycle 4에 geometry를 바꾼 경우에만 `update()` 1회, 나머지 Idle에서는 0회, Close 후 finalize를 확인했다. `tools.native_ui_smoke`도 5 cycle에서 NAS 1개 발행·종료를 통과했다. 실제 창/API 경로 검증이며 마우스 입력·깜빡임의 시각적 전후 비교는 수행하지 않았다. 전체 300개 시험을 이번 수정에서 다시 실행한 것은 아니다.

## 통합 검증 증거

### 2026-10-20 native 형상 확장과 UI 수정

- Native `sphere(radius)`, `cube(side)`, `cylinder(radius,height)`, `dihedral(length,width1,width2,angle_deg)`를 strict JSON·CLI·ONELAB에 연결했다. 치수/origin 단위 변환·좌표 정밀도·잘못된 입력 거부와 변경 시 재생성 요구를 유지한다.
- Sphere는 origin=중심, cube는 최소 모서리, cylinder는 바닥 중심/+Z 축이다. 세 형상은 CAD solid이며 표면 삼각형만 발행한다. Dihedral은 +Z 공통 모서리를 같은 CAD edge로 구성한 두 sheet이며 0<angle_deg<180이다. 첫 판 +Y, 둘째 판 (sin θ,−cos θ,0)을 기준으로 한다.
- 고정 source `.venv`에서 전체 **341 passed in 302.95s**. 새 시험은 단위·origin·bbox·해석적 면적/체적·JSON/UI roundtrip·필드 visibility·치수 변경 무효화·strict 실패·NAS 독립 읽기·좌표/ID/connectivity/PID를 포함한 NAS bytes 반복 일치를 확인했다. Dihedral 45°/90°/135°에서 실제 공통 hinge node와 두 판의 winding·topology·검사를 확인했다.
- 실제 FLTK에서 네 새 예제를 각각 `tools.native_ui_smoke`로 실행해 각 5 cycle·NAS 1개·finalize를 확인했다. 전체 CLI worker 경로도 네 예제 모두 exit 0 / status=ok로 발행했다. 테스트 결과는 `.cache/` 아래에만 두며 원격 게시에 포함하지 않는다.
- Guide: 기존 형상을 포함한 7개 형상 정의·파라미터 표·inline SVG 그림, dihedral MathML 좌표 정의를 추가했다. 총 17 section·24 table·6 MathML·7 SVG. HTML 중첩·목차/로컬 링크·중복 ID·외부 자산 없음·SVG/XML 구조를 확인했다. Headless Edge에서 1440 px/390 px 페이지 가로 넘침·JS 오류·SVG 문자 범위 이탈 없음, 모바일 그림 자체 스크롤, 인쇄 시 그림 폭과 수식 표시를 확인했다. 7개 그림과 모바일 화면을 시각 검토했다.
- 이번 일괄 게시 기준은 문서 PR #18 merge `070a534cc3dd924b90eeb9e102b3edce0c1a4737`이다. 독립 source 이력을 강제 push하지 않고 전달 checkout의 최신 main에서 `codex/native-shapes-ui`로 게시한다. UI 깜빡임 수정도 함께 포함하며 사용자 요청대로 merge 후 해당 PR 작업 branch를 삭제한다.

### 기존 재작성 통합 기록

대상 저장소의 새 모듈 배치에서 **300 passed in 316.63s**를 확인했다. source의 고정 `.venv`를 사용해 전달 checkout의 모듈 폴더에서 전체 시험을 실행했다. 첫 실행은 pytest basetemp 상위 폴더가 없어 실패했으며, 폴더 준비 후 전체를 다시 실행해 통과했다.

```powershell
New-Item -ItemType Directory -Force .cache\tests | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\local
```

모듈 폴더에 설치한 환경에서 위 명령을 사용한다. Windows Gmsh DLL은 pytest의 native FD capture와 충돌한 이력이 있어 프로젝트 설정의 `--capture=sys`를 유지한다. 시험을 건너뛰어 해결한 것이 아니다. 실제 CAD·CLI·Plugin·독립 reader와 실패 주입을 함께 시험한다.

| 영역 | 확인한 성공·실패 경로 |
|---|---|
| 설정 | strict 중첩 schema, 중복/알 수 없는 JSON 키, bool을 숫자로 받는 오류, 음수·비유한·범위 초과·과거 키 거부 |
| 단위·CAD | STEP/STP/IGES/IGS × m/cm/mm/um, 첫 IGES import의 새 프로세스, mixed BREP의 독립 sheet/curve/point·한 번의 scaling·PID 보존, 한글/공백 경로 |
| 품질 Plugin | sparse/reordered element ID 대응, 누락·중복·비유한 결과 차단, 변경 후 Recompute, 기존 view·visibility 보존, 이번 view 정리 |
| topology·방향 | 정상 형상이지만 공유 node가 끊어진 사례, T-junction, nonmanifold edge/vertex, 뒤집힌 winding, solid inward, sheet 기준 누락, 예상 경계/성분과 불일치 |
| 국소 크기장 | 회전에도 같은 최소 폭, 독립 특징별 목표, 공유 경계와 자유 gap 구분, bbox false candidate 이후 실제 거리, 최소 크기·거리 표본, field 변조 |
| 곡률 | 구·원·cylinder·작은 fillet·ogive tip, 200 초과 분할 요구, 극점·seam/null curve 구분, 투영/trim 실패, 편차/최소 크기/재생성 조건 충돌 |
| 개선 | 실제 Relocate2D/Laplace2D, 형상 개선·비악화, 경계 좌표/parameter와 연결/ID/PID/entity 보존, 정확한 rollback, 구조 변경·복구 실패 차단 |
| 현재 상태 | CAD 파일/설정/Physical Group/field/경계 mesh 변경 무효화, 수동 mesh 수정 후 새 검사, CAD 위 node 이동이어도 triangle 편차 초과 시 차단 |
| 발행 | strict NAS와 독립 pyNastran 읽기, 좌표·ID·node 순서·connectivity·PID 변조 차단, 쓰기/읽기 실패 때 pending만 정리·기존 정상 NAS 보존 |
| CLI·UI | 상태 JSON 및 종료 코드, ONELAB idle 중복 발행 없음·오류 Action 소비, 실제 FLTK window/event loop·API-injected Action·finalize, CLI와 NAS bytes 일치 |

Runtime·테스트·예제·개발 도구 60개 파일이 원본 source와 전달 checkout에서 바이트 단위로 일치했고, 게시 최종 tree도 검증한 checkout과 같았다. 루트 설치 wrapper의 `-Dev`/`-UpdateLock` 전달, PowerShell 구문, workspace JSON, README 링크, `git diff --check`도 확인했다. 전달 checkout에서 설치 다운로드 전체를 다시 실행하지는 않았다.

## 품질 정책을 유지한 근거

Gmsh 4.15.2에서 기준 edge (0,0)→(1,0), 세 번째 점 (x,h)의 104개 1차 삼각형을 비교했다. AR≤3·최소각≥20° 조건에 57개가 통과했다.

| (x,h) | AR | 최소각 | Plugin ICN | 현재 정책 |
|---|---:|---:|---:|---|
| (0.5, 0.2) | 2.9979388485 | 21.8014094864° | 0.4384938753 | 통과 |
| (0.5, 3.0) | 2.0728203787 | 18.9246444161° | 0.5329387100 | 차단 |

따라서 단일 ICN 하한으로 기존 수용 집합을 보존할 수 없다. AR·최소각은 유지하고, ICN은 유효 양의 결과 확인 및 개선 후보의 최소값 비악화/상승에 소비한다. 임의의 ICN 품질 하한이나 점수 구조를 추가하지 않는다. 이 사례의 API `minSICN`과 Plugin ICN 최대 차이는 약 `3.23e-15`였지만 고차 요소·부호·sampling의 일반적 동등성으로 확대하지 않는다. 현재 제품은 Plugin 경로 하나를 사용하고 실패 시 다른 measure로 fallback하지 않는다. 개발 도구는 `tools/quality_policy_probe.py`다.

## 대표 기하·재현성 증거

| 사례와 설정 | 기존에 관측한 결과 | 검증의 의미 |
|---|---|---|
| plate 100×60 mm, cap 10 mm | 91 node / 148 triangle / PID 1 | 단계 간 동일 NAS bytes; 단순 기준 사례 |
| mixed BREP mm→m, cap .25 m | 149 node / 280 triangle / PID 1–7 | 독립 CAD root·단위·연결 성분 보존 |
| 얇은 판 10×.6 mm, width divisions=3 | 255 node / 402 triangle, 요청 .2 mm, edge 중앙값 약 .19657 mm | 폭 기반 목표와 실제 edge 길이는 다른 값 |
| 분리 gap .6 / 1.2 mm, divisions=3 | 1314 node / 2380 triangle, 해당 edge 중앙값 약 .2 / .39786 mm | 특징마다 별도 목표; 좌표·연결/PID 포함 반복 일치 |
| R=10 mm 원, δ=.001 mm | 초기 요구 223, 해당 원 경계 실제 line 223개 | 고정 200 clamp 없음. chord 중점 sagitta 독립 확인 |
| R=1 mm sphere, cap .7 / δ=.02 | 421 node / 838 triangle | 독립 연속 radial deviation .013244568771413445 mm < .02 mm; 일반 CAD의 연속 오차 증명은 아님 |
| 26-face fillet BREP, cap .15 / δ=.01 | 2120 node / 4236 triangle / PID 1–26 | 두 번의 전체 NAS bytes 일치, 필요한 기하·품질·독립 발행 통과 |
| 같은 fillet, cap .7 / δ=.01 | 편차 충족, 형상 위반 39개·최소각 13.496° | 편차 통과만으로는 NAS 발행하지 않음 |
| native ogive D2/L3/t0 mm, cap .7 / δ=.02 | 388 node / 749 triangle | 원호 식·면적·열린 base·방향·CLI/FLTK 반복 NAS bytes 일치 |
| native ogive D2/L3/t.2 mm, cap .15 / δ=.02 | 1367 node / 2730 triangle | 단일 벽 두께 solid·독립 단면 적분 체적·outward·CLI/FLTK 반복 일치 |
| 4×4 mm 판, R=.5 hole의 trim 거리 | 내부 hole 쪽 .1 / 외측 1 / face 내부 0 mm | planar trim 최근접 거리와 경계 보정 확인 |

대표 NAS SHA256(모두 고정 입력·build의 기존 관측값):

- plate: `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`
- mixed BREP: `799e166162650b2cd50a99b4dfcccce0afdff15c21118c8aaf21b6e914822e66`
- thin plate: `c93cce75fcdb1c85120d5ea7f95ac67aad9b25719961522169ee070afbf0dc11`
- gap: `662528015265394cdcdc7179a5dd007bd10b4f7fa87641624d7ace349d05a32a`
- native ogive sheet: `bcfab81b5e86a29a1562d74c9f9a14253bfef93d65b732944f17deea6c0504be`
- native ogive wall: `3f0f2c34f593d6428e10adc9b1c308d34941679c8543f0cea3dc9a269440ef45`

재현성은 요소 개수뿐 아니라 좌표·node/element ID·connectivity·PID를 대조한 범위다. 다른 CAD·Gmsh build까지 같은 결과가 된다는 보증은 아니다.

## API 선택과 실패 처리의 보존할 근거

- `DiscretizationError`는 공식 4.15.2 source의 list-based 출력에 원본 element ID와 closest-point 성공 계약이 없어서 채택하지 않았다. CAD API로 ID·trim·round-trip을 확인한다. 검토한 source archive SHA256은 `be3f66f225d27ba9fa014f07e83169285da8a051b0e8ab7103d88066b39bdd3e`다.
- Gmsh 4.15.2의 sphere pole은 미정 주곡률과 zero direction이 나올 수 있어 방향의 유효성을 확인하고 parameter domain 안쪽에서 다시 조회한다. 인접점 곡률은 초기 추정일 뿐 최종 편차 검사를 대신하지 않는다.
- 반복 seam을 상쇄하지 않도록 curvature 경계는 `combined=False`로 읽고 null pole과 구분한다. Curve closest-point parameter는 유효 투영 좌표에서 재구성해 검증한다.
- Trim 밖 투영은 검증된 실제 경계 curve 후보로 보정한다. 평면 최근접 거리와 일반 곡면의 보수적 유효 CAD 점 거리를 구분한다. 실패는 차단한다.
- 첫 IGES import의 OCC unit table 초기화 문제 때문에 disposable in-memory 초기화 read 후 실제 target unit으로 다시 읽는다. 초기화 model은 제거하고 최종 CAD로 사용하지 않는다. 제품은 CAD source를 쓰거나 STEP 중간 변환을 만들지 않는다.
- CLI는 native OCC stdout을 worker pipe에서 capture하고 완료 marker를 확인해 최소 상태 JSON만 내보낸다. DLL file handle을 바꾸거나 제품 log 파일을 만들지 않는다.
- Native ogive는 origin 위치에서 직접 구성하고 생성용 helper를 정리한다. 양의 두께가 단위 변환/좌표 정밀도에서 0으로 사라지면 solid가 sheet로 바뀌지 않도록 입력을 차단한다.

## 한계와 미실행 항목

자동 폭은 단일 loop·직선 경계·볼록 평면만 지원한다. 임의 neck·자기 근접·전체 공간 최소 gap 지도는 아니다. Topology는 node/edge 중심이며 모든 face/face 교차 부재를 증명하지 않는다. 편차는 mesh→CAD 유한 표본이며 양방향 Hausdorff/연속 최대 거리 보증이 아니다. UI의 실제 lifecycle/Action과 자체 FLTK 렌더링을 확인했다. 사용자 창의 마우스 수동 QA와는 구분한다. NAS·기하 검사 통과로 EM 관측량 정확도·수렴을 보장하지 않는다.

## 문서 통합과 이전 기록의 위치

다음 단계 문서는 과거 시점의 미완료 표현과 설명 중복을 줄이기 위해 현재 `docs/`에서 제거했다. 유효한 요구·정책·검증·한계·작업 위치는 guide와 본 기록에 통합했다. 원문은 문서 정리 전 source commit 또는 게시 commit에서 읽을 수 있다. 예: `git show 0e1f4da:docs/stage-5-validation-ko.md`(독립 source), `git show bcf7ad0:02_BRL_mesh_generator/docs/stage-5-validation-ko.md`(대상 저장소).

| 통합한 이전 문서 | 현재 남긴 내용 |
|---|---|
| rebuild-plan-ko.md | 제품 범위·책임 분리·크기장/검사/개선/발행 원리 → guide; 완료 증거·한계 → 본 기록 |
| stage-1 ~ stage-6-validation-ko.md | 단계별 중요한 검증·품질 정책 결정·API 선택 이유·환경/hash → 본 기록; 현재 알고리즘 → guide |
| archive-record-ko.md | 아래 보관 경로·원본 HEAD·미추적 자료 hash·원래 경로 삭제 미완료 상태 |
| github-delivery-ko.md / github-status-ko.md | 아래 저장소·PR·독립 이력/전달 checkout·작업 권한 구분. github-status는 독립 source에만 있었음 |

현재 개발 검증 이전의 단계별 회귀 기록은 38→92→149→240→277→299개였으며 마지막 입력 정밀도 시험 추가 후 게시 배치에서 300개 전체를 통과했다. 상세 중간 시간·run UUID 등은 위 Git 원문에 남기고 현재 사용자 안내에는 반복하지 않는다.

### 로컬 보관 자료

- 기존 프로젝트: `C:\Users\user1\Documents\Codex\99_archive\BRL_2026-10-19`(읽기 전용).
- 보관 HEAD: `3eb636c1be9c2c59103d8f67267686f80ed01659`.
- 보관된 미추적 `docs/mesh-generator-refactor-plan-ko.md` SHA256: `32D218B24302A4EA64D9DFD910E22A4F32F7031DD72AF9A690A8D7796DC2C4EA`.
- 보관된 미추적 `docs/mesh-size-field-guide-ko.html` SHA256: `BA907CEDD591B1D6A3F0046E6CBCF4B9FD5C5DD60EC1536B8ACE663697460C9A`.
- 원래 `Codex\BRL`의 접근 제한 `.pytest_cache`와 안내 파일은 삭제 미완료였으며 이번 작업에서도 건드리지 않았다. 보관 자료·원래 캐시의 권한/삭제 작업은 문서 정리 범위가 아니다.

### GitHub와 다음 작업

- 사용자 지정 저장소: https://github.com/BRL-AIML-students/BRL_AI_EM_convergence.git
- 새 모듈의 저장소 경로: `02_BRL_mesh_generator/`.
- 기존 구현 교체 PR: https://github.com/BRL-AIML-students/BRL_AI_EM_convergence/pull/17 . 2026-10-20 조회에서 merge 완료를 확인했다. Merge commit은 `11e5320d504c1eb7a56fda87a14937565a09c06d`이며 새 문서 PR의 기준 main이다.
- Merge는 명시적으로 요청받은 범위에서 수행한다. 2026-10-20 사용자가 merge까지 요청하면 병합 후 해당 PR의 원격 작업 branch와 대응 로컬 작업 branch를 삭제하도록 지시했다. main과 무관한 기존 branch는 삭제하지 않는다. 이전 guide PR에서 branch를 보존했던 지시는 이 후속 지시로 대체한다. 폴더 통합 설명은 실제 .git·환경 폴더 이동을 승인한 것으로 해석하지 않는다.
- 독립 source: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`, 로컬 `codex/rebuild-core`. 원격 게시 이력과 parent/SHA가 달라 그대로 강제 push하지 않는다.
- 전달 checkout: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator\.cache\github-delivery`; 로컬 `codex/rebuild-published`가 원격 `codex/rebuild-core`를 추적했다. 로컬 별도 `codex/rebuild-core`는 subtree 통합 이력이며 혼동하지 않는다.
- PR #17은 CLI credential manager 대기로 연결된 GitHub API를 사용해 9개 commit으로 게시했다. 메시지와 단계 내용을 유지했고 각 원격 commit 본문에 원본 source SHA를 남겼다. 대응표는 전달 checkout의 `.cache/publish/commit-map.json`에 있다.
- `.cache/github-delivery`는 단순 disposable cache가 아니라 별도 Git checkout이다. 이중 사본을 하나로 통합하는 실제 작업은 이력·미게시 변경·결과를 확인한 후 별도로 수행해야 한다. 이번에는 환경이나 .git 위치를 옮기지 않는다.

## 이번 문서 정리의 확인

- 단일 HTML 17개 장·17개 표·5개 MathML 수식을 작성했다. 태그 중첩·ID 중복·목차 anchor·로컬 링크·외부 자산 의존 없음·제어 문자 여부를 확인했다.
- 실제 dataclass 기본값과 guide 표를 대조하고 파장·전이 거리·55/190 표본 수·223 원호 분할 예를 계산해 확인했다.
- Headless Edge에서 1440 px 데스크톱과 390 px 모바일 렌더링을 확인했다. 페이지 전체 가로 넘침과 JavaScript 오류가 없고 수식이 렌더링됨을 확인했다. 표는 모바일에서 자체 가로 스크롤을 사용한다. Print media에서 목차의 sticky 해제와 수식 표시도 확인했다.
- Sandbox의 브라우저 임시 프로필 접근이 실패해 별도 headless 프로필을 sandbox 밖에서 실행했다. 사용자 브라우저의 기존 탭/프로필을 조작하지 않았다.
- `brl_mesh/`·tests·examples·tools·설치/launcher/의존성 파일에 변경이 없음을 확인했다. 문서 변경에 전체 Gmsh 회귀를 재실행하지 않았으며 위 300개 기록과 구분한다.

## 주요 공식 근거

- [Gmsh 4.15.2 manual](https://gmsh.info/doc/texinfo/gmsh.html): mesh size fields·CAD API·AnalyseMeshQuality·optimize·ONELAB/FLTK.
- [고정 Gmsh source](https://gmsh.info/src/gmsh-4.15.2-source.tgz): DiscretizationError.cpp, OCCFace.cpp, gmsh.cpp. 기존 검토 증거이며 이번 문서 정리에서 전체 source를 새로 빌드한 것은 아니다.
- [Git repository layout](https://git-scm.com/docs/gitrepository-layout), [Python 3.12 venv](https://docs.python.org/3.12/library/venv.html): .git의 역할과 가상환경 이동 제한.
