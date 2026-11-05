# 개발 검증과 유지보수 기록

## 2026-11-05 검사 작업 메모리·중복 계산 개선

- 곡률 편차 계산을 `curvature_sampling.py`로 분리했다. 기본 19-node 격자의 기존 128요소 묶음은 유지하고, 높은 해상도는 총 표본 수에 따라 요소 묶음과 한 요소 내부 격자를 나눈다. 전체 표본 좌표·순서·최대 편차·동률 시 첫 표본의 local feedback seed를 유지한다. 입력 상한이나 축소된 검증 격자를 추가하지 않았다.
- Topology의 edge owner·node incident·fan 관계를 정수 배열로 구성하고 원래의 진단 순서·공유 방향·비다양체 검사를 유지했다. Node/edge 감사의 임시 자료는 삼각형 교차 BVH를 만들기 전에 해제한다. 이전 구현과 무작위 500개 입력에서 issue 순서·연결 성분·경계·인접 크기비가 일치했다.
- 면별 요소 인덱스를 호출 안에서 한 번 구성한다. 법선과 면적 검사는 같은 호출의 인덱스를 공유하고, 변경 가능한 mesh에 걸쳐 캐시하지 않는다. 큰 다각형 폭 측정은 point/normal 행렬을 작은 블록으로 계산하며 rollback 직후의 중복 전 노드 조회를 제거했다.
- 독립 reader는 실제 NAS 검증에서 지연 로딩한다. 생성 전용/UI의 초기 의존성을 줄이되, 발행의 독립 pyNastran 읽기와 대조는 유지한다.
- 전체 회귀는 **583 passed / 651.99초 / exit0**였다. 이는 reader 지연 로딩 직전 source hash `5b4b8d440e38a2a46442bf24c2b627fafe87d25f767a5e8bb0e0baff05faae07`의 결과다. 마지막 지연 로딩·fresh-process 시험 추가 후 NAS·발행·provenance·native worker/UI 대상 **83 passed / 114.17초 / exit0**였다. 최종 source hash는 `3c08fbb70261fc5a0f1092dfc6c607c620e75f1d3fea253870323a907fe5e8cc`다. 최종584항목 전체를 한 번에 재실행한 결과는 아니다.
- 같은 조건의 fresh process를 전후 번갈아 실행했다. 55,560면 판의 3회 시간 중앙값은 25.065→23.839초, 최대 working set은 290.0→245.4MiB였다. 14,038면·곡률 구·221,780면도 동일 node/triangle수·NAS mesh cards SHA-256과 낮아진 peak를 관측했다. 시간 편차가 커 일반적인 속도 향상을 보장하지 않는다. 221,780면은 전후 각1회다. 시간은 의존성 import부터 종료까지 포함해 지연 로딩 비용을 빠뜨리지 않는다.
- n=1000 합성16삼각형에서 8,008,000표본을 모두 처리했고 최대 projection 호출24,320점, NumPy/helper 프로세스 peak46.3MiB였다. 실제 CAD/NAS가 없는 합성 사례다. Native55,560면 headless 생성의 부모+worker working set 표본 합은 356.3→271.7MiB, private commit은3189.1→1896.3MiB였다. 공유 페이지와 virtual commit을 실제 고유 RAM과 구분한다. 실제 FLTK/GPU·장기 누수·대형 assembly는 새로 측정하지 않았다.
- 로컬 `.cache/optimization-20261105/수정및검증결과.md`, raw JSON·로그·XML·고정 baseline·독립 검토가 상세 근거다. 독립 검토에서 지적한 타일별 투영 허용값 회귀를 보완하고 큰 오프셋·전체 span·trim 대체점의 회귀를 추가했다.

### 2026-11-05 GitHub 게시 사전 검증

- Git의 LF 정규화를 적용한 전달 모듈의 제품 source hash는 `5568a4ea06da80c46c5c136f859e758597818b9cec0cef1e371ca80fc3fc8746`다. 위 Windows 로컬 검증 raw hash와는 줄바꿈 표현이 달라 별도로 기록한다. Python 내용은 LF 정규화 후 일치한다.
- 최신 원격 main `9ed78e2c8185d5ba180216a545c919ce1b3c0e8a` 기반 전달 checkout에서 곡률 표본·topology·교차·작업 배열·NAS·provenance·native worker 대상 **152 passed / 86.04초 / exit0**을 확인했다. 실제 import 경로와 전달 모듈 hash도 확인했다.
- 게시 파일은 모듈 내부 runtime·관련 테스트·guide·개발 검증 문서 19개로 한정한다. cache·가상환경·생성 NAS·개인 설정은 포함하지 않는다. 게시 기록과 manifest·XML·로그는 로컬 `.cache/optimization-20261105/release/`에 둔다.

정리일: 2026-10-20. 사용 흐름·알고리즘·변수·발행 조건은 [사용자 guide](mesh-generator-guide-ko.html)를 기준으로 읽는다. 이 파일은 개발 증거와 이력 연결을 보존하며, 제품의 실행 보고서가 아니다.

## 2026-11-04 최종 회귀 및 대표 측정

최종 제품 source hash `436ba81d7e29ee3944981754ca7971d5f0f97b4e75ea4e3ddf650d58d3f7dc6d`가 불변인 상태에서 전체 회귀 **548 passed / 679.76초 / exit 0**을 확인했다. 증거는 `.cache/audit-20261102/optin-final.log`, XML, exit 및 source-hash 파일이다. 대상 74건·19건·38건은 별도 단위/대상 시험이다.

다음은 기존 entity 방식과 local 방식의 두 사례 비교다. 각 pure 실행 3회 중앙값이며 측정 여건과 형상에 한정한다. 편차 ratio는 표본 편차를 허용값으로 나눈 값이며, 두 local 결과 모두 이 표본 조건을 통과했지만 기준보다 편차가 크다.

| 사례 | 시간 entity → local | triangles entity → local | 영역 밖 triangles entity → local | 표본 편차 ratio entity → local | 최소각 entity → local | 최대 AR entity → local |
|---|---:|---:|---:|---:|---:|---:|
| local-bend | 18.175 → 16.552초 (−8.93%) | 440 → 354 | 112 → 51 | 0.446 → 0.620 | 30.90° → 32.27° | 1.960 → 1.709 |
| sphere | 1.708 → 1.615초 (−5.42%) | 966 → 786 | 해당 없음 | 0.441 → 0.855 | 37.35° → 21.27° | 1.630 → 2.874 |

구의 local 결과는 품질 조건은 통과했지만 최소각과 최대 AR의 여유가 줄었다. 16회 실행(각 pure 3회와 계측 1회, 두 방식·두 사례)에서 전체 계약·독립 NAS 검증·제품 source hash 일치를 확인했다. 계측 실행은 시간 중앙값에 포함하지 않았다. 두 사례의 속도나 표본 편차로 모든 CAD의 성공, 일반적 속도 향상 또는 EM 정확도를 보장하지 않는다. 원자료는 `.cache/performance/local-curvature-optin-20261104/results.json`과 `.cache/audit-20261102/final-measurement-summary.json`이다.

실제 FLTK API 주입 실행은 fresh process에서 작은 판 44개와 큰 판 55,560개 삼각형을 각각 한 번 성공했다. 큰 판의 observer 제외 event-pump 진입 간격 최대 208.43 ms, loop body 최대 144.98 ms이며 adopt 94.34 ms, 첫 명시 draw 36.33 ms, helper 17.17 ms, main commit 1.35 ms였다. 단계는 중첩될 수 있고 이전 UI와 비교한 수치가 아니다. 마우스 입력·첫 픽셀·GPU 완료·모든 환경의 최대 멈춤은 측정하지 않았다. 같은 프로세스에서 두 번째 FLTK 초기화 시 access violation이 발생했으나 별도 새 프로세스의 큰 판은 성공했으며 원인은 확정되지 않았다. 개발 probe는 한 프로세스에 한 사례·한 번만 허용한다. 원자료는 `.cache/performance/native-fltk/`의 `optin-fltk-20261104-tcuwv9uf/results.json` 및 `optin-fltk-large-fresh-20261104-q6ztbbp8/results.json`이다.

HTML 시각 QA는 Chrome headless 실행 실패와 IAB file URL 정책 차단으로 미완료다.

## 2026-11-04 현재 S2/O5 검증 상태

S2는 `mesh.curvature.feedback`의 기본값 `entity`를 유지하고 `local`을 명시 선택할 때만 위반 표본 주위 크기장을 적용한다. 기존 편차·품질·독립 NAS 검증은 유지하며 실패 시 차단한다. O5는 NAS 복사·hash를 helper thread에서 수행하고 main thread에서 현재성을 재확인해 확정한다. 변경된 임시 경로와 외부 추가 파일은 보존하고 정리 실패를 경고한다. Provenance는 schema 3이다. 곡률 관련 대상 74건(291.744초), 정리·소유권 19건, 설정·provenance·UI 38건이 통과했다. 최종 전체 회귀 548건이 통과했고 대표 성능 측정의 조건과 한계는 아래에 기록했다.

확장 중 전체 회귀는 538 passed/4 failed, 후속 대상 실행은 92 passed/2 failed였다. 기본 전면 feedback 교체에서 드러난 ogive 관련 실패를 해결하기 위해 검증된 entity 방식을 기본으로 복원하고 local을 선택 사항으로 분리했다. 분리 후 곡률 관련 대상 74건이 통과했으나 이 결과는 모든 CAD에서 local 성공을 뜻하지 않는다. 이후 최종 전체 회귀 548건이 통과했다.

Windows는 검증한 대상 파일의 deny-write handle을 commit 직전 닫고 곧바로 rename하므로 그 사이 외부 경쟁이 남는다. 비 Windows에서는 main thread에서 다시 hash한다. Gmsh adopt·render·검사와 rename은 main thread에 남으며 무정지를 보장하지 않는다.

## 현재 기준과 변경 범위

- 고정 환경: Python 3.12.14, uv 0.12.20, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1, pytest 8.4.2. `pyproject.toml`, `uv.lock`, `.python-version`으로 환경을 관리한다.
- Gmsh DLL SHA256: `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`. 이 build의 식별값이며 다른 build의 동일 결과 보증이 아니다.
- 문서 정리 전 source commit: `0e1f4daf2d5f5cf4253671499e517b83d4d1870f`.
- 문서 정리 전 게시 head: `bcf7ad0460d07c7dd01db297fe86136c7923b277`, tree `9964f2ab9ad2f78eb3965ec9d5a3594325968bd8`.
- 앞선 문서 정리 작업은 guide·README·개발 지침만 변경했다. 아래 통합 수치 시험은 당시 기존 실행의 기록이며 문서 작업 중 새로 수행한 결과가 아니다.

## 2026-10-20 후속 코드 점검

후속 코드 점검은 아래 수정이 PR #20으로 병합된 source `38d459e` / 게시 main `60d10631051dcf75066ae0a907d33be7f0a810aa`를 기준으로 진행했다.

- 곡률 계획의 면–curve 인접 관계는 각 면의 경계를 한 번만 읽어 구성한다. `combined=False`, seam 중복 제거, 정렬된 인접 face와 null pole 처리를 유지한다.
- 편차 측정은 해당 face의 connectivity만 좌표로 변환한다. 각 face마다 전체 mesh의 삼각형 좌표 배열을 다시 만들던 중복 할당·검색을 제거했다.
- 기존 commit의 `CurvaturePlan`과 수정본을 같은 실제 CAD/mesh에서 실행해 curve/face/point 인접 관계, 허용값, 모든 `(dimension, entity, element ID, deviation)` 및 entity별 ratio가 정확히 같음을 확인했다. Sphere 984개, ogive 770개, 26-face fillet 3,077개 측정값 전체를 대조했다.
- 계획 구성 중 face 경계 API 호출은 sphere 4→1회, ogive 14→2회, fillet 1,482→26회로 감소했다. 같은 환경의 단회 편차 측정 시간에는 일관된 감소가 없었으므로 전체 생성 속도 향상을 수치로 주장하지 않는다. 측정 표본·허용값·품질/발행 기준은 그대로다.
- 관련 회귀 `tests/test_curvature.py tests/test_reassessment.py`는 **35 passed in 113.63s**였다. 실제 곡면 재분할, projection/trim 실패 차단, 변경된 mesh/경계 재검사, minimum-size 충돌, UI 표시·기본 전환·NAS 발행을 포함한다. 직전 전체 회귀를 다시 반복하지 않았다.

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

## 2026-10-21 생성 시간·NAS 용량·ONELAB 응답 개선

### 원인과 변경 범위

- 수정 전 source HEAD는 `0b5113a5b28f08f85b1716c142aa3f9b63fd1645`다. `01_mesh_generator`는 보관 source를 읽어 비교했으며 실행·수정하거나 새 runtime에서 import하지 않았다. 아래 성능 비교의 기준은 **새 구현의 수정 전/후**이며, 옛 `01_mesh_generator`와의 실행 시간 비교로 해석하지 않는다.
- 곡면 형상으로 전환할 때 UI가 Curvature를 강제로 켜고 상대 허용값 0.001을 넣었다. 구 R=1 mm, Target size=0.4 mm에서 OFF는 194 triangles / 11,214 bytes, 해당 조건 ON은 4,872 triangles / 309,307 bytes였다. 목표 길이 입력만 같아도 실제 이산화 조건과 요소 수는 같지 않았다. 형상 변경은 이제 기존 활성 상태·허용값을 보존한다. JSON에 명시한 곡률 조건은 유지한다.
- 옛 writer와 새 writer는 모두 17자리 유효숫자의 free-field GRID/CTRIA3를 쓴다. 이번에는 좌표 자릿수를 줄이거나 허용오차를 완화해 용량을 줄이지 않았다. 동일한 실제 메쉬의 NAS 크기는 유지하며 의도하지 않은 세분화를 제거한다.
- cProfile에서 판 100×60 mm, h=1 mm, 14,038 triangles의 전체 11.56 s 중 topology가 8.30 s, `generate`는 0.22 s였다. 구 R=10 mm, h=0.5 mm, 12,100 triangles에서는 전체 16.54 s 중 topology 9.02 s, normals 4.52 s였다. 이 시간은 profiler를 켠 값으로 일반 사용의 wall-clock 측정과 구분한다.
- Topology AABB 후보 검색을 node별 Python 순회에서 최대 2,048개 point 묶음으로 변경했다. 표면 분리·보호 gap·정밀도·T-junction 판정은 유지한다. Solid 법선은 batch의 모든 점이 안/밖으로 분류됐을 때만 공통 부호를 확정하며 혼합 batch는 기존 개별 판정으로 돌아간다. 대표 점 하나의 방향을 전체에 적용하지 않는다.
- Trim 밖 표본의 분류는 정렬된 unique UV의 subset count를 분할하고 자식 count 합과 원래 count를 대조한다. 개별 ctypes 호출을 줄이며 trim 실패 차단·실제 표본 개수·허용값은 유지한다. 곡률 ON의 조밀한 CAD 표본 검사는 여전히 비싼 작업이다.
- 기존 UI는 FLTK main thread에서 생성·검사·개선·독립 NAS 읽기를 모두 수행했다. 실제 launch는 이제 Gmsh를 별도로 소유하는 subprocess에서 이 작업을 실행하고, main thread는 `fltk.wait(0.05)`로 이벤트를 처리한다. 서로 다른 thread가 같은 Gmsh model을 동시에 조작하지 않는다. UI 표시와 완료 CAD import는 main thread에서 수행한다.
- 내부 MSH 4.1 binary에 모든 차원·parametric node를 저장하고 전송 뒤 좌표·연결·ID·PID·surface digest 및 point/curve 경계를 정확히 대조한다. Gmsh 4.15.2의 MSH merge가 기존 Physical Group membership을 중복 추가하는 동작을 확인해, 직렬화된 group을 복원한 뒤 원 CAD fingerprint와 대조한다. 실패하면 발행을 차단한다.
- 현재 메쉬의 source hash·CAD·field·경계 참조 검사와 최종 재검사, ICN, rollback, 독립 pyNastran 검증을 유지한다. NAS는 worker의 로컬 작업 폴더에서 검증하고 UI가 현재 설정·mesh의 일치를 확인한 뒤 최종 위치로 복사·hash 대조·rename한다. 취소/충돌/worker 비정상 종료의 중간 결과는 최종 NAS가 되지 않는다.
- Job은 `.cache/native-jobs/job-*` 한 폴더를 소유하고 완료/취소 때 그 폴더와 자식 process를 정리한다. 사용자 출력·보관 source·기존 cache 전체를 삭제하지 않는다. 매우 작은 메쉬에는 process 시작과 전송 비용이 추가된다. 큰 CAD의 완료 import나 화면 그리기 지연까지 없다는 보장은 하지 않는다.

### 기능·응답 검증

- `tests/test_native_job.py`: 실제 subprocess에서 plate, sphere, ogive, cube, cylinder, dihedral, 원형 BREP의 Generate → Improve → Publish가 CLI NAS와 byte 단위로 같다. 실행 중 설정 변경·메쉬 변경·이미 불량인 현재 메쉬·worker crash·중복 Action·취소를 검증한다.
- 수정 전 source를 로컬 `.cache/perf-original`에 복사해 비교했다. 무작위 triangle 연결, 1 / 10^-6 / 10^6 축척, 비스듬한 정확한 T-junction을 포함한 60건에서 issue/code/status, 연결 성분 수, 열린 경계, 인접 크기 비율이 모두 같았다. 별도 회귀는 2,048 point batch를 넘는 oblique T-junction을 검사한다.
- 실제 FLTK 창의 dense plate 14,038 triangles에서 53회 event pump, 최대 pump 간격 0.266 s를 기록했다. 상대 허용값 0.001인 sphere 4,872 triangles에서는 153회, 최대 0.344 s였다. 이는 API로 Action을 입력한 lifecycle/응답 측정이며 사용자의 마우스 수동 조작 시험은 아니다.
- 재현 도구: `python -m tools.performance_probe --label <이름> [--plain --repeat 3 --case plate --case sphere]`, `python -m tools.native_ui_smoke <configuration.json>`. 측정 NAS·profile·JSON과 smoke 산출물은 `.cache`에만 둔다. 제품에는 NAS 한 파일만 전달한다.
- 회귀 실행: `pytest --basetemp=.cache/perf-tests-all`은 349건 중 347건 통과, 2건은 이전 자동 곡률 활성화 정책을 기대한 assertion이었다. 해당 2건을 형상 전환의 opt-in 유지와 명시적 곡률 활성화 검증으로 갱신한 후 `tests/test_reassessment.py` 10건이 모두 통과했다(46.62 s). 전체 실행 후 추가한 thin_plate/gaps subprocess 왕복과 2,048-point 초과 T-junction 3건도 통과했다(10.23 s). 현재 수집되는 352개 항목을 이 실행들로 모두 확인했으며, 최종 코드에서 352건을 한 번에 재실행했다는 뜻은 아니다.
- Guide의 중복 ID·누락 anchor·외부 CSS/JS 의존과 이전 자동 활성화 안내가 남아 있지 않은지 확인했다. 이번 guide 변경은 기존 레이아웃의 문장 수정이며 브라우저 전체 시각 QA를 새로 수행한 것은 아니다.

### Profiler 없이 3회씩 순차 측정한 최종 비교

같은 Python/Gmsh 의존성, 같은 형상·목표 길이·곡률 OFF·기본 개선 설정으로 CLI 코어의 생성부터 독립 NAS 검증까지 측정했다. 수정 전 6회 후 수정 후 6회를 실행했으며 다른 이번 작업의 테스트/benchmark를 동시에 돌리지 않았다. 프로세스 시작·ONELAB 표시 시간은 이 표에 포함하지 않는다. 중앙값이며 모든 입력의 속도 보장은 아니다.

| 조건 | 수정 전 중앙값 (범위) | 수정 후 중앙값 (범위) | 상대 속도 | NAS |
|---|---:|---:|---:|---|
| 판 100×60 mm, h=1 mm, 14,038 triangles | 9.40 s (6.25–10.23) | 4.13 s (1.75–4.38) | 2.28배 | 772,724 bytes, 전후 동일 |
| 구 R=10 mm, h=0.5 mm, 12,100 triangles | 11.59 s (11.51–12.40) | 6.13 s (6.03–6.23) | 1.89배 | 765,109 bytes, 전후 동일 |

두 조건의 각 6개 NAS는 node/triangle 수·바이트 수·SHA256가 모두 일치했다. 별도의 profiler 4조건(곡률 OFF 조밀 판·구, coarse 구, 상대 곡률 ON 구)에서도 전후 NAS가 모두 동일했다. 최종 상세 JSON은 `.cache/performance/summary.json`, 원본 wall-clock 결과는 `.cache/perf-original/.cache/performance/before-plain/results.json`과 `.cache/performance/after-plain/results.json`에 있다.

## 2026-10-21 ONELAB wave 기본 활성화

- 사용자 요청에 따라 native `launch`에서 wave가 생략된 시작 설정에 `Wave(1e9)`를 적용한다. 시작값은 1 GHz·파장당 요소 수 10·상대 유전율/투자율 각 1이다. 명시된 wave 설정은 보존하고 실행 중 체크 해제도 허용한다.
- 기본값은 Controller에 전달할 설정에 먼저 반영해 worker 실행과 설정 변경 감지가 같은 조건을 사용한다. 원래 Configuration과 JSON 파일은 변경하지 않는다. CLI에서 wave 생략 시 OFF라는 schema 의미도 유지한다. Target size가 활성화되어 있으면 기존처럼 두 길이 중 작은 값을 사용한다.
- `tests/test_native_ui.py`와 `tests/test_sizing_config.py` 70건 통과(3.16 s). 기본 ON·사용자 주파수/매질 보존·체크 해제·원 설정 불변·기존 idle/Action 동작을 확인했다. 실제 FLTK `tools.native_ui_smoke examples/plate.json`에서 비동기 생성·NAS 검증·발행·종료를 확인했다(30 event pumps, 최대 간격 0.296 s).

## 2026-11-02 전범위 점검 후 개선 — 진행 기록

기준 점검은 로컬 `.cache/audit-20261102/검토결과.md`와 source commit `4659b8b252c56dc27661cf87ce8f52137026ec4a`에 기록했다. 아래는 변경 중인 작업 트리의 상태이며 최종 통합 결과가 아니다. 기준 코드의 354건 회귀와 이전 성능 측정은 변경 후 결과가 아니다.

- R1: 삼각형 AABB 후보와 국소 좌표 판정으로 내부 교차·공면 중첩을 검사하고 불확실한 경우 차단한다. 정상 공유 경계와 양의 gap을 구분한다. 회전·이동한 얇은 판과 비공면 비공유 단일점 접촉 보완은 대상별 시험에서 확인했다. 부동소수점 검사는 exact arithmetic 또는 연속 형상 오차의 증명이 아니다.
- R2: Gmsh 4.15.2의 실제 background 선택을 로컬 임시 `.geo_unrolled` 직렬화에서 읽어 생성 참조와 대조한다. field 목록이 비어 있을 때의 미등록 활성 ID도 대조한다. 관련 XAO 등 임시 파일은 전용 폴더에 둔다. 이 검사는 대형 CAD에서 직렬화 시간·디스크 비용이 들 수 있으며 성능 측정은 남았다.
- R3/R4: `output_dir`만 바뀌면 현재 mesh의 전체 발행 재검사를 거쳐 새 위치에 발행할 수 있다. 생성에 영향을 주는 다른 설정은 기존처럼 재생성이 필요하다. 삼각형 품질 정규화에는 요소별 국소 edge 척도를 사용한다.
- O1: 검사 1회 안에서 삼각형 좌표·외적·크기를 read-only로 공유해 shape/normals/geometry의 일부 중복을 제거한다. 외부 진입과 ICN 직전 현재성 확인은 유지하며, 영구 캐시나 topology 전체 자료 공유는 구현하지 않았다.
- O2/O4/D4: 곡률 편차 계산은 동일 entity·bounded batch 안에서 정확히 동일한 표본의 투영을 재사용하고 원래 표본과 요소별 최대값을 보존한다. NAS 자체 검사는 줄 단위로 읽으며 독립 pyNastran 검사 전에 자체 검사 자료를 해제한다. 로컬 stage에서 검증한 NAS만 목적지 임시 폴더에 복사해 SHA-256 대조 후 확정한다. Native worker 경로의 추가 로컬 복사 성능은 아직 측정하지 않았다.
- S3/D1: 같은 메쉬 상태에서 거부된 개선 방법의 무의미한 반복을 중단한다. 형상 실패에는 최대 AR·최소각·위반 요소 수를 표시한다. curve sampling은 실패 구간에 더 이상 표현 가능한 parameter를 추가할 수 없거나 coverage 실패 시 전체 구간의 수치 정밀도가 소진되면 차단한다. 기존 표본·spacing·chord 조건을 유지하며 plateau만으로 중단하지 않고 임의 표본 수·반복 상한을 추가하지 않는다. 모든 실패의 entity/element 정보와 기하 충돌 조기 진단은 아직 구현 범위가 아니다.
- S4: 별도 취소 action은 창을 유지한다. worker 실패·취소 시 현재 설정과 CAD/field/경계/기존 mesh가 확인될 때만 이전 scene을 유지한다. adopt 중 Gmsh 모델이 바뀐 뒤의 복원은 보장하지 않고 차단한다. worker 종료를 확인하지 못하면 취소 대기 상태에서 새 작업을 차단하고 재시도를 허용한다. UI Close도 worker 종료 확인 전에는 창을 유지하며, OS 창이 이미 닫힌 경우 종료 미확인과 PID를 오류로 알린다. 확정 후 임시 정리 오류는 완료된 NAS 발행 상태와 경로를 유지하며 별도로 표시한다. CLI 성공 stdout은 status/nas_path만 포함하고 경고는 stderr로 보낸다.

각 작업의 대상별 시험 결과와 한계는 로컬 `.cache/audit-20261102/*-progress.md` 및 `IMPLEMENTATION.md`를 참조한다. 1차 통합 회귀는 **406 passed, 376.21초**였으나, 이후 접촉·빈 field·정리/종료 경계 보완 전의 결과다. 그 후에는 각 담당 대상별 시험만 확인했다. **후속 경계 보완과 BVH 최적화 직후 회귀는 446 passed, 378.39초(exit 0)**였다. 이 결과는 이후 D2 provenance 변경 전의 결과다. 성능 비교는 아래에 기록한다. 향후 결과가 나오면 조건과 함께 별도로 기록한다.

### 2026-11-02 BVH 부분 최적화와 순차 성능 비교

신규 교차 검사 BVH의 leaf 크기와 중복 AABB mask 계산을 조정했다. 후보 집합과 중복 여부를 exhaustive 및 실제 메쉬와 비교하고 관련 시험 68건이 통과했다. 이는 O3의 BVH 순회 일부이며 topology 전체 배열화, 국소 크기 감사 공간 인덱스와 대규모 CAD·peak memory 평가는 남았다.

같은 조건에서 profiler 없이 각 사례를 3회씩 순차 실행한 중앙값이다. 기준은 source commit `4659b8b252c56dc27661cf87ce8f52137026ec4a`이며, 최초 개선 뒤 BVH 순회를 최적화한 현재 코드와 비교했다. 외부 시스템 부하는 통제하지 않았다. 시간은 전체 생성부터 NAS 검증·발행까지의 측정이며 일반적인 모든 CAD의 속도를 의미하지 않는다.

| 조건 | 기준 | 최초 개선 | BVH 최적화 후 | 기준 대비 최종 변화 |
|---|---:|---:|---:|---:|
| plate, 14,038 triangles | 1.849 s | 3.294 s | 2.485 s | +34.36% |
| sphere_auto_curvature, 4,872 triangles | 8.446 s | 8.904 s | 8.780 s | +3.95% |

각 조건에서 기준·변경 후 NAS SHA-256, node 수와 triangle 수는 같았다. 별도 동일 mesh에서 **신규 교차 함수만** 교대로 3회 측정한 중앙값은 BVH 수정 전 대비 plate 약 54.9%, 구 약 46.8% 감소했다. 이는 전체 작업 속도 향상률이 아니며, 전체 실행은 위 두 사례 모두 기준보다 오래 걸렸다. 비교 자료는 로컬 `.cache/audit-20261102/benchmark-comparison.json`, 함수 단독 자료는 `.cache/audit-20261102/intersection-traversal/timing.json`에 있다. 외부 EM solver 수렴과 대형 assembly 검증은 수행하지 않았다.

후속 경계 보완과 BVH 최적화 후 전체 회귀는 446 passed, 378.39초(exit 0)였다. 이후 D2 provenance 변경은 이 회귀에 포함되지 않는다.


## 2026-11-03 NAS 생성 참조 provenance

NAS 단일 파일의 `$ BRL-PROV` 주석에 당시 schema 2의 canonical ASCII JSON을 SHA-256과 순번이 있는 base64 조각으로 기록한다. 직접 `nas.write` 호출에서 provenance 생략은 지원되며, 메타데이터가 있으면 strict reader는 chunk·hash·schema를 검사한다. 유효 설정의 중첩 항목은 기존 설정 parser를 재사용하며 CAD 경로만 내부 대체해 원본 파일이 없는 환경에서도 검증한다. 일반 설정 입력은 기존대로 CAD 원본 파일 존재를 요구한다. 발행 경로는 원 생성 참조와 정확히 대조한 뒤 독립 pyNastran의 node/element ID·좌표·연결·PID 검사를 수행한다.

생성 참조는 output_dir을 제외한 유효 설정, 파일 CAD 원본 bytes SHA-256(파일이 없는 native 형상은 null), generator/Gmsh 버전, 설정된 mesh/thread 옵션, `brl_mesh/*.py` 직접 파일의 상대 경로와 bytes를 길이 접두로 결합한 source hash를 포함한다. Git base commit과 Git이 확인한 해당 범위의 tracked 및 무시되지 않은 untracked 파일의 dirty 여부는 별도 표시하며 Git을 사용할 수 없으면 null이다. base commit이나 clean 표시는 실행 중 메모리의 코드가 commit과 정확히 같다는 증거가 아니다. 파일 읽기와 생성·검사 사이의 변경을 원자적 snapshot으로 보장하지 않는다. 실제 내부 알고리즘·실제 thread 수·개선 이력은 확인되지 않아 null이다. CAD 경로는 기존 형상 주석과 유효 설정에 포함될 수 있다.

원 생성 참조는 canonical 문자열로 보관하고 native worker의 생성 결과 및 현재 메쉬 action에 전달한다. 발행 시 설정·CAD·코드 범위·설정 옵션을 재확인하며, 원 참조를 모르면 임의로 생성 이력을 만들지 않고 차단한다. Direct writer의 provenance 생략은 별도로 지원되는 API다.

대상 시험에서 plate/sphere CLI와 worker의 NAS bytes 동일성, 현재 mesh action 3/4, 출력 위치 변경, 코드 hash 및 CAD 변경 차단, 주석 변조·schema 위반 차단, mesh card 불변을 확인했다. 이전 446건 전체 회귀와 위 성능 수치는 이 provenance와 후속 S3 변경 전 결과다. 변경 후 전체 회귀 및 성능 측정 결과는 아래 2026-11-03 통합 재검증 절에 기록했다.


## 2026-11-03 S3 표본화 정밀도 소진

`curve_sampling`은 CAD 값·parameter bounds·표본 좌표와 chord의 유효성을 확인한다. Spacing을 위반한 구간에 표현 가능한 parameter를 더 이상 넣을 수 없거나, chord coverage 조건이 실패한 상태에서 모든 구간의 parameter 정밀도가 소진되면 `sampling_precision_conflict`로 차단한다. 기존 sampling 방식, 최대 chord/spacing 및 chord 합/CAD 길이 조건을 유지한다. 일시적인 plateau만으로 중단하지 않으며 임의의 표본 수 또는 반복 상한은 없다. 최종 `tests/test_curve_sampling.py` 15건이 통과했다. D2/S3 변경 후 전체 회귀와 성능 측정 결과는 위 통합 재검증 절에 기록했다.

S1 알고리즘 재시도의 승인된 일부 구현과 대상별 시험은 아래 후속 기록을 참조한다. 실제 CAD 성공률은 측정하지 않았다.


## 2026-11-03 D2/S3 통합 재검증과 성능 비교

최초 전체 회귀는 4 failed, 473 passed, 385.71초였다. 세 실패는 정수와 실수 설정의 정규화 차이, 한 실패는 provenance가 다른 설정의 전체 NAS bytes 비교에 따른 것이었다. 설정 정규화를 통일하고 후자는 mesh card 동일성과 metadata 차이를 별도로 검증한 뒤 전체 회귀 **478 passed, 381.77초(exit 0)**였다. 실행 시작과 종료 시 제품 소스 hash가 같았다.

Profiler 없이 사례당 3회 순차 실행한 중앙값은 plate 2.514초, 곡률 구 8.728초였다. 기준 commit의 각각 1.849초, 8.446초에 비해 **35.97%, 3.34% 증가**했다. 외부 시스템 부하는 통제하지 않았다. 기준·provenance 이전·현재의 node 수, triangle 수와 주석을 제외한 NAS mesh card SHA-256은 각 사례에서 같았다. provenance 주석 추가에 따라 전체 NAS bytes는 의도적으로 달라졌다. 원자료는 로컬 `.cache/audit-20261102/provenance-sampling-comparison.json`과 `provenance-sampling-final.log`에 있다. 이는 두 사례의 측정이며 대형 CAD나 EM 정확도에 관한 결론이 아니다.


## 2026-11-03 S1 품질 재생성과 O3 국소 감사 부분 구현

- `generation.quality_retry`는 `none`이 기본이고 `delaunay`를 명시하면 새 생성의 기존 개선이 정상 반환되고 비형상 검사·양의 ICN은 통과했지만 형상 조건만 불합격인 경우에 한해 기본 요청 Algorithm 6에서 Algorithm 5로 한 번 재생성한다. CLI 및 native Action 1/2에 적용하며 현재 mesh Action 3/4에는 적용하지 않는다. 실제 Gmsh generate 예외의 재시도는 지원하지 않는다. 재생성 후보도 전체 검사와 독립 NAS 검증을 통과해야 한다. 왜곡을 주입한 회귀는 분기와 차단을 확인한 것이며 실제 CAD 성공률·속도 향상의 증명이 아니다.
- 생성 옵션의 `generation` 키를 반영해 NAS provenance schema는 2다. Algorithm 5로 요청한 재생성의 참조는 해당 요청 옵션을 보존하며, 외부에서 현재 옵션을 바꾼 상태는 발행 전에 차단한다. 실제 Gmsh 내부 알고리즘·fallback 및 실제 thread 수는 여전히 unknown이다. 이전 schema 1 provenance에 대한 묵시적 호환은 제공하지 않는다.
- O3 국소 크기 감사는 curve projection query가 4개 이상인 경우에만 유한 batch 안에서 동일 surface·동일 midpoint를 재사용한다. 서로 다른 surface는 합치지 않고 1–3개 curve와 Box-only는 기존 경로를 유지한다. 모든 대상 시험에서 전후 ratio는 정확히 같았다. 대표 width 사례(1,602 triangles)의 local audit만 교대 순서 각 3회 중앙값이 8.334→6.166 ms로 약 26% 감소했고 작은 width에서는 이득이 거의 없었다. 단일 curve는 원 경로이며 측정 변동이 있다. 전체 workflow 또는 모든 CAD의 향상으로 해석하지 않는다. 원자료는 `.cache/audit-20261102/local-audit-timing-20261103.json`.

이 변경 후 전체 회귀와 메모리 benchmark 결과는 아래 최종 검증 절에 기록했다.


## 2026-11-03 S1/O3 이후 최종 회귀와 NAS 메모리 측정

S2/O5 확장 전 제품 소스 hash가 시험 후에도 동일한 조건에서 전체 회귀는 **513 passed, 385.88초(exit 0)**였다. 앞선 478건은 이 변경 이전 기록이다. 로컬 원자료는 `.cache/audit-20261102/retry-local-final.log`, XML 및 exit 파일이다.

Profiler 없이 각 사례를 3회 순차 실행한 전체 작업 중앙값은 다음과 같다. 외부 시스템 부하와 파일시스템 cache는 통제하지 않았다.

| 사례 | 기준 | 현재 | 기준 대비 |
|---|---:|---:|---:|
| 판, 14,038 triangles | 1.849초 | 2.524초 | +36.48% |
| 곡률 구, 4,872 triangles | 8.446초 | 8.787초 | +4.03% |

두 사례 모두 node·triangle 수와 주석을 제외한 NAS mesh card SHA-256은 기준과 일치했다. 이 결과는 전체 속도 향상이 아니라, 추가 검사 등을 포함한 현재 전체 작업이 해당 기준보다 오래 걸렸다는 측정이다. 원자료: `.cache/audit-20261102/retry-local-comparison.json`.

별도 `tools/nas_memory_probe.py`로 합성 fan mesh에서 NAS writer·검증 및 hash 연산을 분리해 각 조건을 한 번씩 측정했다. 아래 메모리는 Windows의 **프로세스 생애 전체 최대 working set**으로 import·입력 mesh 구성 등을 포함하며, Python tracemalloc이나 검증 단계만의 순수 peak가 아니다. 독립 pyNastran 검증을 유지했다. 직접 writer는 provenance 주석을 생략하고, hash는 native worker의 `read_bytes`/`file_digest` 연산을 모사하며 worker 전송 전체를 측정하지 않는다. 외부 부하·cache를 통제하지 않은 단회 합성 사례다.

| triangles | NAS 검증 peak 기준 → 현재 | 검증 시간 기준 → 현재 | hash 별도 프로세스 peak 기준 → 현재 |
|---|---:|---:|---:|
| 10,000 | 112.559 → 107.145 MiB | 0.198 → 0.195초 | 24.758 → 24.309 MiB |
| 100,000 | 327.742 → 269.031 MiB | 2.197 → 2.122초 | 30.262 → 24.477 MiB |
| 1,000,000 | 2,441.297 → 1,872.336 MiB | 23.447 → 22.374초 | 92.680 → 24.387 MiB |

100만 요소 검증의 프로세스 peak는 이 한 사례에서 약 23.3% 낮았다. 이 수치로 실제 CAD, UI 전체 메모리 또는 일반적인 성능을 보장하지 않는다. 로컬 원자료는 `.cache/audit-20261102/nas-memory-10k-100k.json`, `nas-memory-1m.json`이다.


## O5 native 단계의 제한적 측정

Headless 상태에서 각 사례·action을 3회씩, 총 12회 측정했으며 모두 성공했고 동일 사례의 NAS hash가 일치했다. 표는 각 단계의 중앙값(초)이다. 생성·발행 Action 1의 adopt는 CAD/MSH를 가져오고, 현재 mesh 발행 Action 4의 adopt는 기존 mesh를 대조한다. Worker 대기는 NativeJob 생성 이후부터 측정하며 worker 시작과 생성 단계가 겹칠 수 있다.

| 사례 / action | job 초기화 | worker 대기 | adopt | NAS 전달 확정 |
|---|---:|---:|---:|---:|
| 판 / 새 생성·발행 | 0.0083 | 3.657 | 0.0367 | 0.0090 |
| 판 / 현재 mesh 발행 | 0.0441 | 2.518 | 0.0478 | 0.0097 |
| 곡률 구 / 새 생성·발행 | 0.0082 | 9.763 | 0.0269 | 0.0088 |
| 곡률 구 / 현재 mesh 발행 | 0.0315 | 7.044 | 0.0222 | 0.0090 |

이 값은 headless 동기 단계 시간이며 실제 FLTK 창·render·event pump를 측정하지 않았다. 따라서 UI 응답 지연이나 최대 멈춤 시간을 뜻하지 않는다. Probe가 추가 수행한 전체 mesh 검사와 최종 독립 NAS 검사는 위 단계 시간에 넣지 않았다. 대형 CAD도 측정하지 않았으며 이 수치는 O5 비동기화 전 측정이다. 원자료는 로컬 `.cache/audit-20261102/native-stages-summary.json`과 그 안의 source 경로에 있다.

## 2026-11-03 S2/O5 확장 통합 중간 검증

- 기준 전체513회귀 이후 S2 face-local sampled-deviation feedback과 O5 순수NAS I/O 비동기화를 구현했다. 모든 기존 gate·Gmsh main-thread·독립 pyNastran 대조를 유지한다. 다음 수치는 확장 전 기록을 대체하는 성공 선언이 아니다.
- S2 대상69건 54.197s exit0, O5 file/barrier19건 exit0. 전체 회귀는 `local-ui-final.log/xml`에서 **4 failed, 538 passed, 402.46s, exit1**. 시작/확인 source hash `c01d986fd8bb96c889510fd83ea95f3c1552eac4e7296ea996a4e3ac40844acb` 일치.
- 당시 세 실제 회귀는 native/worker ogive의 형상조건과 상대편차 iteration 소진이었다. 한 건은 필렛의 이전 전면feedback 요소수4256 고정 기대값(현재4296); 동일입력 NAS 재현성과 최종gate는 통과했다. 숫자 고정은 최종계약/재현성 검사로 대체했다. 이후 entity 기본/local 선택 설계와 대상 시험 결과는 맨 위 현재 상태를 참조한다.
- O5는 helper 완료까지 job/source/pending 소유권을 유지하며, 변경된 폴더/파일과 외부 추가파일을 정리 대상으로 삼지 않는다. Windows의 검증된 target은 쓰기를 거부하는 handle을 commit 직전까지 유지한다. 부모디렉터리 rename을 위해 handle close 후 즉시 rename하며 그 사이 외부경쟁은 원자적으로 보장하지 않는다. 비 Windows는 main thread 재hash 경로다.
- 통합 HTML은 기존본문16장·MathML6·SVG7을 보존하고 현 동작으로 수정했다. IDs27/내부anchor42/로컬링크/외부자산/중첩 검증과 예제JSON13개 확인을 완료했다. 현재판 화면검증은 Chrome headless 실행 실패 및 IAB file URL 정책 차단으로 미완료다. 정책우회는 하지 않았다.
- 대표 국소곡률 성능 및 실제 FLTK event-pump 측정 결과는 위 최종 측정 절을 참조한다. 원자료는 `.cache/audit-20261102` 및 개발용 tools에 보존하며 제품 산출물은 mesh.nas 하나다.
