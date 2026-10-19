# BRL mesh generator 재작성 계획

작성일: 2026-10-19, 갱신일: 2026-10-20. 상태: 0–6단계의 로컬 구현·자동 통합 검증 완료. GitHub 대상은 BRL-AIML-students/BRL_AI_EM_convergence로 확정했고, 기존 구현 교체 PR을 준비한다. Merge는 명시적 지시를 기다린다. 자원 검사는 native 호출 전후의 협력적 검사이며 강제 native 중단/allocator 제한은 아니다. UI의 마우스/외관 시각 QA는 미실행이다.

## 확정한 작업 위치

- 새 프로젝트: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`
- 기존 프로젝트 보관: `C:\Users\user1\Documents\Codex\99_archive\BRL_2026-10-19`
- 기존 코드 기준: `3eb636c1be9c2c59103d8f67267686f80ed01659`
- 새 독립 환경: Python 3.12.14, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1, pytest 8.4.2. 프로젝트 안의 별도 `.tools`·`.venv`·`.cache`에서 설치·import를 확인했으며 의존성은 `uv.lock`으로 고정한다.

## 제품 흐름

`ONELAB 또는 CLI → 설정·단위 확인 → CAD 구성 → 크기장 구성 → 표면 메쉬 생성 → Plugin 기반 요소 품질 및 별도 topology·법선 검사 → 개선 가능 여부 판단 → 필요 시 Gmsh mesh.optimize → 현재 메쉬 재검사 → 수용 또는 정확한 rollback → 임시 NAS 쓰기·독립 읽기 검증 → NAS 한 건 발행`

설정·실행 코어·검사 결과·출력 계약을 새로 설계한다. 구조 재작성과 수치 동작 변경을 구분해 차례로 검증한다. 기존 프로그램을 동작하게 유지하기 위한 임시 호환 코드는 만들지 않는다.

## 포함·제외 범위

| 대상 | 새 프로젝트의 요구 |
|---|---|
| 실행 | ONELAB 중심, 같은 코어를 사용하는 단일 실행 CLI |
| 입력 | 명시적인 새 설정 schema, 형상·길이 단위·주파수·크기·개선·출력 설정 |
| 형상 | 필요한 기본 형상과 STEP/IGES/BREP; 단위와 mixed BREP의 독립 sheet/curve 보존 |
| 메쉬 | 1차 삼각형 표면 메쉬, 선택한 설정으로 한 건 생성 |
| 크기장 | 전역 목표·특징별 국소 목표·전이·곡률 편차·자원 제한의 책임 분리 |
| 개선 | 필요 시 Relocate2D/Laplace2D, 연결·PID·entity 보존과 비악화 판단, 정확한 rollback |
| 요소 품질 계산 | `AnalyseMeshQuality`의 Jacobian·ICN·IGE를 우선 검토하고 실제 판정에 필요한 measure만 선택; AR·최소각 정책의 유지/전환은 검증 후 확정 |
| 별도 필수 검사 | 유한 좌표·유효 연결·중복·topology·T-junction·nonmanifold·예상 경계·CAD/기준 방향 법선·기하/크기 보존; 퇴화는 품질 계산 실패와 함께 차단 처리 |
| 출력 | 검사 통과 후 현재 메쉬와 좌표·ID·connectivity·PID가 일치하는 NAS 한 건 |
| 출력 실패 | 미완료·미지원 검사를 성공 처리하지 않고 발행 차단, 기존 정상 결과 보존 |
| 상태 | 진행·완료·차단·짧은 원인·NAS 경로 등 최소 상태 |
| 제외 | 브라우저 UI·HTTP 서버·NAS viewer·조건 조합별 비교·controlled 비교 모드·case 분기 |
| 제외 | score·등급·scoring profile·결과 보고서·diagnostic mesh·독립 진단 view·log 파일 |

설정 JSON과 개발 검증 문서는 결과 보고서 삭제 범위와 구분한다. 제품에 장황한 진단을 되살리지 않되 실행 실패 원인과 필수 검사 상태는 확인할 수 있어야 한다.

## 설계 원칙

1. ONELAB과 CLI는 설정을 같은 내부 구조로 전달한다. UI에 별도 계산 로직을 만들지 않는다.
2. 원시 검사값과 통과/차단 사유를 점수 구조 없이 제공한다. 생성·개선·출력이 실제로 소비하는 검사만 제품 경로에 둔다.
3. Gmsh size field·CAD/mesh API를 활용하고, 요소 형상 품질 계산은 `AnalyseMeshQuality`를 우선 활용 대상으로 설계한다. BRL은 계산된 값의 판정·개선 제어를 맡으며 같은 품질 수식을 기본적으로 재구현하지 않는다. 자동화 경로·지표·버전 검증 후 Plugin 또는 적합한 API 경로를 확정한다. `DiscretizationError`는 편차에 따른 생성 판단에 실제 필요한 경우에 검토한다.
4. `Smooth`를 mesh node 이동 대용으로 취급하지 않는다. ICN을 기존 AR 또는 MoM 행렬 조건수와 동일하게 취급하지 않는다.
5. 기존 설정 키나 Action 숫자는 자동 승계하지 않는다. 새 예제를 제공하고 미지원 입력은 명시적으로 거부한다.
6. CAD·설정·현재 메쉬가 바뀌면 이전 검사 상태를 무효화한다. NAS 발행 직전 실제 현재 메쉬를 검사한다.
7. 임시 NAS는 독립 pyNastran 읽기까지 통과한 후 발행한다. 실패 시 이번 실행의 임시 파일만 정리한다.
8. 새 runtime에서 보관 폴더를 import하거나 보관된 가상환경을 실행하지 않는다. 필요한 구현은 출처와 계약을 검토한 후 옮긴다.

## Plugin·API·BRL의 책임

아래 표의 계산 경로와 책임 분리는 최종 설계다. 2단계에서 ICN의 실제 개선 수용 연결, 일반화된 내부 topology·법선 검사, 개선/rollback을 구현했다. 기존 AR·최소각을 유지하는 정책으로 확정했으며 3단계에서 CLI의 STEP/IGES/BREP 입력과 같은 코어를 사용하는 ONELAB을 연결했다. Plugin이 제공하는 요소별 유효성·형상 정보를 전체 connectivity 또는 CAD outward normal의 보증으로 해석하지 않는다.

| 항목 | 우선 활용 기능 | 필요한 BRL 연결·판정 코드 | 별도 검증 기준 |
|---|---|---|---|
| 요소별 Jacobian·ICN·IGE | `AnalyseMeshQuality` 계산; 소비자가 있는 measure만 활성화 | 현재 mesh의 element ID에 결과 대응, 의미·유한성·누락 확인, 선택한 기준으로 통과/차단 | 정상·가늘고 찌그러진·퇴화 삼각형, ID 순서 변경·누락 |
| AR·최소각 정책 | 정책을 유지할 때 필요한 별도 계산 또는 적합한 검증된 API | 유지 이유와 계산 정의 명시; ICN과 중복되는 검사 확대를 기본으로 하지 않음 | 기존 기준과 ICN의 수용/거부 차이, 아래 전환 절차 |
| 유효 연결·중복 요소·분리/중복 노드·T-junction·nonmanifold | Gmsh node/element·adjacency API와 필요한 BRL 코드 | ID 기반 연결과 필요한 공간 관계 확인, 기대한 연결·부품 구성과 대조 | 요소 품질은 좋아도 공유 연결이 끊어진 사례·T-junction·nonmanifold 차단 |
| 열린 경계·gap | CAD 경계·entity 관계·사용자 의도를 나타내는 설정 | 의도한 열린 sheet/분리 gap과 예상치 못한 틈 구분; 근접 좌표 무단 병합 금지 | 의도한 경계/gap은 허용하고 기대한 공유 경계의 단절은 차단 |
| 법선·winding | Gmsh CAD normal·solid 경계 방향 정보와 필요한 BRL 코드 | 인접 요소 winding 및 solid 바깥 방향 대조; 열린 sheet는 명시한 기준 방향에 대조 | 뒤집힌 winding·CAD outward 불일치 차단; 기준 없는 sheet는 필요한 방향 검사를 미완료로 처리 |
| 개선 실행·수용·rollback | `gmsh.model.mesh.optimize`의 `Relocate2D`/`Laplace2D` | 개선 가능 여부, 횟수 제한, 전후 검사, 불변량·기하/크기 비악화·정확한 복구 | 악화 후보 거부; 연결·ID·PID·entity 변경은 발행 차단 |
| NAS 최종 출력 | NAS writer와 독립 pyNastran reader | 현재 mesh 재검사, 좌표·ID·connectivity·PID 대조, 검증 후 발행 | 정상 round-trip 및 변조·읽기 실패 시 정상 NAS 미발행 |

여러 부품이 의도적으로 분리된 형상은 그 자체로 오류가 아니다. topology 판정에는 기대 연결과 허용 경계가 필요하다. Plugin의 표시 숨김은 요소 수정·삭제·연결 복구가 아니며, 숨겨진 요소를 검사나 NAS 출력 대상에서 자동 제외하지 않는다.

### AR·최소각에서 ICN 중심 기준으로 전환하는 절차

기존 AR·최소각 기준을 ICN 임계값으로 그대로 환산하지 않는다. ICN은 MoM 행렬의 조건수나 EM 정확도 보증이 아니다. 기존 필수 검사는 새 기준이 확정되기 전에 검증 없이 없애지 않는다.

1. 기존 AR 정의·최소각 정책·차단 목적과 Plugin 지표의 정확한 의미를 정리한다. 기존 정책의 보존 필요성을 먼저 판단한다.
2. 정상·가늘고 찌그러진·퇴화 요소와 실제 CAD의 대표 메쉬에서 두 기준의 수용/거부 및 개선 전후 변화를 개발 과정에서 비교한다. 숫자 임계값은 이 설계 단계에서 임의로 정하지 않는다.
3. 기존 정책을 유지하면 AR·최소각을 별도 계산해야 하는 이유를 남긴다. 기존 기준을 유지하면서 ICN·IGE까지 모두 제품 차단 기준으로 추가하지 않는다. 사용하지 않는 measure는 끈다.
4. ICN 중심으로 바꾸면 누락되는 실패 유형이 없는지 검증하고 새로운 기준·적용 범위·실패 처리를 확정한다. 그 후 불필요해진 AR·최소각 경로를 제거한다. 이는 과거 입력/반환값 호환 계층을 유지하는 작업과 구분한다.
5. 단계 2의 완료 조건에 품질 정책과 계산 경로 확정을 포함한다. 개발 비교는 제품의 점수화·비교 일괄 생성 기능으로 제공하지 않는다.

**2단계 결정:** Gmsh 4.15.2에서 104개 삼각형을 비교했다. 기존 기준에 통과한 사례의 ICN은 약 0.438인데 탈락한 다른 사례의 ICN은 약 0.533이었다. 따라서 단일 ICN 하한으로 기존 수용 집합을 보존할 수 없다. AR ≤ 3·최소각 ≥ 20°를 유지하고, Plugin ICN은 유효 결과 확인과 개선 후보의 최소 ICN 비악화/상승 판단에 사용한다. 임의의 새 ICN 품질 임계값을 만들지 않는다. IGE·Jacobian 경로는 현재 소비자가 없어 채택하지 않는다. 이 비교와 Plugin/API 선택 근거는 [2단계 기록](stage-2-validation-ko.md)에 남긴다.

### 표면 메쉬용 Plugin 호출·결과 읽기 설계

공식 동작의 근거는 [Gmsh 4.15.2 AnalyseMeshQuality 설명](https://gmsh.info/doc/texinfo/gmsh.html#Plugin_0028AnalyseMeshQuality_0029)이다. ICN adapter의 ID 대응·재계산·임시 view 정리·표시 상태 보존과 실제 개선 연결은 검증했다. Jacobian/IGE는 현재 사용하지 않으며 아래 해당 설명은 향후 필요할 때 지켜야 할 해석 기준이다.

| 옵션·단계 | 적용 설계 |
|---|---|
| `DimensionOfElements=2` | 현재 검사 대상인 표면 요소로 명시적으로 제한 |
| `JacobianDeterminant`·`ICNMeasure`·`IGEMeasure` | 매 호출에 선택을 명시. ICN 중심 정책의 시험에서는 `ICNMeasure=1`; Jacobian은 유효성 판정에 필요한 경우 활성화하고 IGE는 실제 소비자가 없으면 0. 세 measure를 관례적으로 모두 켜지 않음 |
| `Recompute=1` | 생성·좌표 이동·복구 등 mesh 변경 후 다시 계산. 이전 view와 품질값을 재사용하지 않음 |
| `CreateView=1` | Plugin 결과를 코드에서 읽는 경로를 선택하면 임시 model-based view를 사용. 제품의 독립 진단 화면·보고서·파일을 생성하는 목적이 아님 |
| 결과 대응 | 생성된 view를 식별하고 데이터 종류·element ID·필요한 모든 요소의 포함 여부를 확인. 배열 순서가 mesh ID 순서와 같다고 가정하지 않음 |
| Jacobian 결과 해석 | Plugin의 Jacobian 계산과 view의 `min(J)/max(J)`를 구분. view 값을 원시 `min(J)`로 취급하거나 CAD 바깥 방향 판정에 대신 사용하지 않음 |
| 표시 상태 | `HidingThreshold`·`ThresholdGreater`는 표시 기능으로만 취급. 자동 검사에서는 숨김을 사용하지 않는 설정과 실행 전후 표시 상태 보존을 검증 |
| 정리·실패 | 이번 호출이 만든 view만 성공·실패 경로 모두에서 정리. 미완료 계산·누락 ID·비유한 결과·Plugin 오류를 정상 통과로 바꾸지 않음 |

필요한 원시 결과는 메모리의 `element ID → measure 값`으로 관리하고 별도 pass/blocked/incomplete 및 이유를 반환한다. `scores`·등급·보고서 구조를 복원하지 않는다. Plugin 통계가 출력되는 경로도 확인하여 제품 보고서·진단 파일로 저장하지 않는다.

자동화 적합성은 [getElementQualities API](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002fmesh_002fgetElementQualities) 경로와 비교 검증할 수 있다. 예를 들어 API의 `minSICN`/`minSIGE` 이름만으로 Plugin의 ICN/IGE와 같은 정의·부호·sampling·수치라고 가정하지 않는다. 선택 근거는 지표 의미, element ID 대응, 실패/미완료 처리, view 수명, 버전별 동작이다. 최종적으로 한 정책에 맞는 경로를 선택하며, Plugin 실패 때 의미가 다른 API로 조용히 대체하지 않는다.

### 검사·개선·발행 상태 흐름

1. 현재 mesh에서 유한 좌표·참조 가능한 node ID 등 입력 유효성을 확인한다. 품질 계산이 정의되지 않는 손상 입력은 먼저 차단한다.
2. 선택한 Plugin 기반 요소 품질과 별도 topology·법선 검사를 수행한다. 필수 검사가 미완료면 발행하지 않는다. 법선은 solid 바깥 방향과 열린 sheet 기준 방향을 구분한다.
3. topology·방향 등 재배치로 해결할 수 없는 문제가 있으면 이 개선 경로를 중단한다. 정상 topology에서 요소 형상 개선이 필요한 경우만 다음 단계로 간다.
4. node ID·좌표·connectivity·PID·entity 분류 등 복구와 보존 판정에 필요한 현재 상태를 확보하고, 제한된 횟수 안에서 `mesh.optimize(Relocate2D/Laplace2D)`를 실행한다.
5. 변경된 현재 mesh를 `Recompute=1`로 다시 평가하고 topology·법선·기하/크기 보존도 다시 확인한다. 선택한 형상 기준의 개선과 필수 조건의 비악화가 확인되면 수용한다.
6. 수용하지 못하면 좌표를 정확히 복구하고 복구된 현재 mesh를 재검사한다. 연결·ID·PID·entity가 달라져 좌표 복구만으로 원상태가 되지 않으면 발행을 차단하고 중단한다. 불량 topology를 노드 이동으로 해결했다고 처리하지 않는다.
7. 최종 현재 mesh의 필수 검사 통과 후 임시 NAS를 쓰고 독립 읽기에서 좌표·연결·PID를 검증한 뒤 발행한다. 표시 여부와 무관하게 출력 대상 전체를 확인한다.

## 크기장 개선 요구

- 전역 길이는 적용 가능한 파장·사용자 상한·fallback 조건의 지배 관계를 명시한다. 모든 계산은 같은 출력 단위를 사용한다.
- 최소 크기 하한·자원 예산이 필수 요구와 충돌하면 요구를 조용히 완화하지 않고 정책에 따라 중단하거나 미충족을 명시한다.
- 짧은 edge·좁은 면·분리 gap·곡률·수동 영역을 구분하고 특징별 목표를 계산한다. 전체 최소 특징 하나를 모든 특징에 공유하지 않는다.
- 공유 경계 거리 0을 분리 gap으로 처리하지 않고 근접 좌표를 자동 병합하지 않는다. 미지원 폭·자기 근접 측정은 명시한다.
- 작은 크기 유지 범위와 전이 거리를 분리한다. 거리 field sampling에 따른 안정성을 검증한다.
- 곡률 제어는 편차와 국소 반경에 연결한다. 기존 200은 BRL의 원당 목표 입력 상한이며 Gmsh의 실제 생성 요소 수 제한으로 취급하지 않는다.
- Plugin 표본 편차·요청 길이·실제 edge 길이·전자기 결과 수렴을 구분한다.

4단계에서 명시 상한·파장·fallback의 지배 관계, 특징별 독립 목표, Distance/Threshold/Restrict/Box/Min, 유지와 전이 분리, 하한 충돌 차단을 구현했다. 자동 폭은 단일 loop·직선 경계의 볼록 평면에 한정하고 그 외 요청은 미지원으로 차단한다. 분리 gap은 bbox 후보 이후 실제 CAD 최소 거리를 확인하며 같은 연결 성분/solid 내부 면·접촉을 구분한다. field metadata와 실제 요소·CLI/ONELAB NAS를 확인했다. 세부 범위와 전체 자원 한도가 아직 없는 점은 [4단계 기록](stage-4-validation-ko.md)에 구분한다.

## 구현 단계와 완료 기준

| 단계 | 작업 | 통과 기준 |
|---|---|---|
| 0 | 기존 BRL 보관·새 작업 루트·계획 정리 | Git HEAD·미추적 문서 보존, 새 프로젝트 독립성 |
| 1 | 새 설정·데이터 구조·CLI·생성부터 NAS까지 최소 코어, Plugin/API 읽기 경로 소규모 검증 | 개발용 단순 판에서 NAS round-trip·불량 입력 차단·element ID 대응 확인, 새 환경 재현; 단계 2 전 일반 CAD의 필수 검사 완료로 간주하지 않음 |
| 2 | Plugin 우선 요소 품질 계산·별도 topology/법선·개선/rollback | 품질 정책·계산 경로 확정, 점수 의존 없음, 좋은 형상이지만 연결이 끊어진 메쉬·잘못된 방향 차단, 악화·연결 변경 거부 |
| 3 | ONELAB·CAD·단위·PID·법선 연결 | CLI와 같은 코어, 실제 현재 메쉬 발행, STEP/IGES/BREP·mixed BREP·열린 경계 검증 |
| 4 | 특징별 크기장·전이 | 특징 독립성, 폭·gap·하한 충돌, 적용 옵션과 실제 요소 확인 |
| 5 | 편차 기반 곡률·필요 시 DiscretizationError feedback·자원 제한 | 원당 목표 200 초과 요구, 구·작은 필렛·ogive tip·미충족 처리; 요소 품질 Plugin 설계는 단계 1·2에서 검증 |
| 6 | 통합 검증·기본 실행 경로 확정 | 단순·복잡 CAD, 정상/실패 NAS, 부가 산출물 없음, 문서·실행 경로 일치 |

현재 완료 상태: 0–6단계의 로컬 구현·자동 검증 완료. [5단계](stage-5-validation-ko.md)의 CAD API 편차 feedback과 협력적 자원 제어에 이어 [6단계](stage-6-validation-ko.md)에서 native ogive D/L/t·trim 경계 편차·복잡 CAD 재현성·CLI/FLTK를 통합 검증했다. 원래 BRL 경로의 접근 제한 캐시 삭제, 수동 UI 시각 QA, GitHub 처리는 완료로 표시하지 않는다. 보관본·원래 캐시·권한은 변경하지 않았다.

각 단계는 검증 가능한 크기로 나누어 구현하고 필요한 테스트·예제·UI/CLI·문서를 함께 관리한다. 단계 1이 동작하기 전에는 새 생성기가 완료됐다고 표현하지 않는다.

CLI/ONELAB은 native 판(+Z), tangent-ogive D/L/t(+Z), STEP/IGES/BREP 파일을 지원한다. 3단계의 mixed BREP·단위·PID·방향·현재 mesh 검사와 6단계의 native ogive 및 trim 경계 처리를 연결했다. 각 단계 기록은 당시 범위와 제한을 구분하며 향후 다른 primitive는 별도 요구에 따라 확장한다.

현재 개선 설정은 `improvement.enabled=true`, `max_passes=3`이 기본이며 max_passes는 0–10 정수다. 개선을 꺼도 필수 검사와 NAS 발행 차단은 유지한다. topology 기대 경계와 연결 성분은 관측된 삼각형의 구멍 대신 CAD 경계·surface adjacency에서 구성한다. 분리 의도와 sheet 방향은 CAD schema/ONELAB 입력과 연결했으며 필요한 검사를 생략하지 않는다. 설정·CAD source SHA256·CAD topology/기하 fingerprint·Physical Group/PID·point/curve mesh 경계의 생성 참조가 바뀌면 재생성을 요구한다. 현재 mesh의 검사는 발행 직전에 다시 수행한다.

### 로컬 개발과 최종 GitHub 처리

2026-10-19 사용자 지시로 단계별 branch·PR·merge 방식 대신 다음 흐름을 적용한다.

1. 이 프로젝트의 로컬 `codex/rebuild-core` branch에서 단계별로 파일을 작성하고 해당 단계의 검증·기록·의미 있는 commit을 남긴다. 구현 단계마다 GitHub push·PR·merge를 하지 않는다.
2. 전체 로컬 구현·통합 검증이 끝나면 변경 범위와 검증 결과를 모아 최종 PR을 준비한다. 원격 대상은 사용자 결정에 따른다. 보관된 BRL remote를 자동 재사용하거나 새 저장소를 임의로 공개하지 않는다.
3. Merge는 사용자의 명시적 지시를 받은 뒤에만 수행하고, 의미 있는 commit을 보존하는 merge commit을 사용한다.
4. 그 merge가 성공했음을 확인한 뒤 기본 branch로 전환하고 해당 작업 branch를 로컬·원격에서 정리한다. 삭제 전 미병합 commit·사용자 변경·다른 worktree 사용 여부를 확인한다. 병합 실패나 미완료 작업이 있으면 branch를 보존한다.

현재 단계의 로컬 작업 지시는 즉시 원격 게시·merge·branch 삭제를 허가한 것으로 해석하지 않는다.

## 검증 사례

- 단순 판: 전역 크기·파장·단위·CLI/ONELAB 설정 일치.
- 구·원 경계·cylinder: 곡률·법선·200 초과 목표·실제 편차.
- 긴 얇은 판·서로 다른 작은 특징·분리 gap: 폭/간극·특징 독립성·의도한 경계 보존.
- 작은 필렛·ogive tip·복잡 CAD: 국소 특징·특이점·실패 범위 명시.
- 정상·가늘고 찌그러진·퇴화 삼각형: 선택한 품질 measure의 유한성·수용/거부·정책 전환 검증. 기존 AR·최소각과 ICN 임계값을 동일시하지 않음.
- 좋은 형상의 삼각형들로 구성됐지만 기대한 공유 연결이 끊어진 사례: Plugin 형상 품질 통과 여부와 별개로 topology 차단.
- 잘못된 연결·중복 요소/노드·T-junction·nonmanifold·예상치 못한 열린 경계: 별도 검사로 차단. 의도한 열린 경계·독립 부품·gap은 그 자체로 차단하지 않음.
- 뒤집힌 인접 winding·CAD solid outward와 불일치·열린 sheet 기준 방향 불일치: 별도 법선 검사로 차단. 필요한 기준이 없으면 미완료를 정상 통과로 처리하지 않음.
- 개선 악화·연결/ID/PID/entity 변경: 수용 거부와 정확한 rollback 또는 발행 중단. 복구 후 품질을 재계산하고 필수 검사 재수행.
- Plugin 결과 ID 순서 변경·누락·비유한 값·예외: 잘못된 요소에 품질값을 연결하거나 성공으로 처리하지 않음.
- 생성·개선·rollback 후 재계산: 이전 mesh의 cached 품질/view로 판정하지 않음. 성공·실패 후 임시 view 누적 및 검사 때문에 생긴 표시 상태 변화가 없음.
- NAS 변조·쓰기/읽기 실패: 정상 NAS 미발행, 기존 정상 파일 보존.
- 동일 동작을 보존하는 경우: 같은 CAD·Gmsh build·설정·알고리즘·thread·seed 아래 좌표와 connectivity/PID를 비교한다.
- 알고리즘이 의도적으로 달라지는 경우: 이전 좌표와 일치시키는 대신 해당 변경의 기하·크기·topology 요구를 검증한다.

AR·최소각의 기존 운영 조건을 유지할 경우 그 근거와 적용 범위를 명시한다. ICN 중심 전환은 사례 검증으로 별도 확정하며 기하·NAS 검사 통과는 EM 정확도 보증이 아니다.

## 근거

로컬 보관본의 `99_archive/BRL_2026-10-19/docs/mesh-generator-refactor-plan-ko.md`의 최종 범위를 이어받는다. 기존 코드를 순서대로 삭제하는 이전 구현 절차는 위 재작성 절차로 대체한다. 새 폴더명과 보관 경로는 사용자의 2026-10-19 지시에 따른다.

2026-10-19 side conversation의 사용자 요청으로 Plugin의 요소 품질 계산, 별도 topology·법선 검사, BRL 판정·개선 제어의 책임을 본 설계에 반영했다. 공식 문서는 기능 범위의 근거이며, 실제 2단계 구현·정책 결정·검증 범위는 해당 검증 기록으로 구분한다.

- [Gmsh 4.15.2 AnalyseMeshQuality](https://gmsh.info/doc/texinfo/gmsh.html#Plugin_0028AnalyseMeshQuality_0029): 제공 measure·model-based view·표시 숨김·재계산 옵션의 근거.
- [getElementQualities](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002fmesh_002fgetElementQualities), [getModelData](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fview_002fgetModelData): 자동화 경로·ID 대응 검증 시 참고할 공식 API 설명.
