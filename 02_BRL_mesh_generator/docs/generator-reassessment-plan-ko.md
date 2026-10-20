# Generator 재검토 및 수정 계획

작성일: 2026-10-20. 상태: 사용자 승인 후 구현 반영. 1–5절의 진단 수치는 수정 전 기준이며, 구현 결정과 검증은 6절 및 validation-ko.md를 따른다.

## 1. 결론과 검토 범위

원래 목표는 `01_mesh_generator`의 형상 생성·크기 제어·개선·정상 NAS 발행 흐름을 보존하면서, 같은 역할을 수행하는 Gmsh API/field/Plugin으로 구현을 줄이는 것이었다. 현재 구현은 원호 기반 ogive, native size fields, ICN Plugin, 개선 rollback, NAS 독립 읽기를 보존했다. 그러나 크기 제어의 기본 동작과 알고리즘 선택이 바뀌었고, 사용자 설정에 대한 생성 성공 및 화면 표시 검증이 부족하다. 현재 결과를 기존 방식과 동등한 리팩터링이라고 평가할 근거는 충분하지 않다.

기존 계획에는 곡률 허용오차와 국소 크기 제어를 개선하는 변경도 포함되어 있었다. 따라서 모든 차이를 회귀로 단정하지 않는다. 의도한 정책 변경과 실제 결함을 분리해 수정한다.

- 현행 source: `cdd74a1becd689db96b91a1edeaed4412268b3df`, Gmsh 4.15.2, 프로젝트 `.venv`.
- 비교 source: 읽기 전용 `99_archive/BRL_2026-10-19`, 기준 commit `3eb636c1be9c2c59103d8f67267686f80ed01659`.
- 검토 경로: 설정 → OCC 형상 → 전역/국소/곡률 크기 제어 → 삼각형 생성 → 검사/개선 → NAS 발행 → ONELAB/FLTK 표시.
- 실험은 독립 headless Gmsh session에서 수행했다. 사용자 Gmsh 창을 조작하거나 제품 outputs에 새 NAS를 발행하지 않았다.
- 기존 전체 테스트 통과는 개별 계약에 대한 증거다. 사용자 D50/L100 조건의 성공, 기존 전체 파이프라인과의 동등성, 오른쪽 화면의 가독성을 입증하지 못했다.

## 2. 확인된 문제와 아직 확정하지 않은 부분

### A. 화면에 보인 실패는 실제 생성 차단이다

첨부 화면의 `Blocked: width_unsupported`는 `features.polygon_width()`가 곡면 ogive에 평면 다각형 폭 측정을 적용하면서 발생한다. 현재 지원 범위는 직선 경계의 볼록 평면이다. 이 옵션을 ogive에서도 선택할 수 있고, 실행 중 기존 model을 지운 뒤 실패한다.

따라서 그 실행에서는 새로운 ogive NAS가 발행되지 않는다. 화면에 남은 CAD 선이나 이전 파일 읽기 메시지를 새 결과로 해석하면 안 된다. 필요한 조치는 형상별 지원 범위 표시, 생성 전 입력 검사, 실패 시 결과 상태의 명확한 분리다.

### B. 곡률 옵션을 켠 사용자 규모에서도 추가 차단을 재현했다

아래 조건으로 국소 옵션을 모두 끄고 생성만 시험했다. 첨부 화면 전체를 그대로 재현한 것은 아니며, Widths 오류와 독립적인 곡률 문제를 분리한 시험이다.

```json
{
  "schema_version": 1,
  "geometry": {"kind": "ogive", "diameter": 50, "length": 100, "thickness": 0},
  "length_unit": "mm",
  "output_unit": "mm",
  "mesh": {
    "target_size": 10,
    "minimum_size": 0.01,
    "wave": {"frequency_hz": 1000000000},
    "curvature": {"absolute_tolerance": 0.01, "relative_tolerance": 0.001}
  }
}
```

약 31.7초 뒤 다음 오류로 차단됐다.

```text
curvature_callback_incomplete: curvature_minimum_conflict:
required=0.01, applied=0.00691539, minimum_size=0.01
```

별도의 추적 재현에서는 첫 mesh가 24,916삼각형이고 표본 편차/허용값의 최대 비율이 1.33913임을 확인했다. 경계 curve의 비율은 모두 1 미만이었지만 두 face가 약 1.33828/1.33913으로 실패했다. 그 뒤 face와 인접 curve의 배율을 줄인 재생성에서 위 충돌이 발생했다. 따라서 이 조건은 조밀한 초기 mesh를 만들지 못하는 문제가 아니라, 편차 판정 후 재생성을 완료하지 못하는 문제다. 첫 판정은 sampling_nodes=10 단계이므로 verification_nodes=19 검증을 통과한 결과가 아니다.

현재 `curvature.refine()`은 위반한 face 전체의 크기 배율을 줄이고 인접 경계 curve에도 배율을 전달한다. `size()`는 곡률 기반 초기 크기에 이 배율을 다시 곱한다. 오류의 `required`는 초기 계산값, `applied`는 재분할 배율을 곱한 값이다. 따라서 이 메시지만으로 실제 기하가 반드시 0.00691539 mm 요소를 필요로 한다고 결론 내릴 수 없다.

끝점의 곡률 특이성, 표본의 CAD 투영, face 전체 재분할의 상호작용을 분리해야 한다. 허용오차나 최소 크기를 조용히 완화해 성공시키는 방법은 사용하지 않는다.

### C. 곡률 제어가 꺼진 경우, 거친 곡면 근사가 정상 검사 결과가 될 수 있다

동일한 현행 생성·검사 API로 측정했다. 반경 편차는 삼각형 중심의 z에서 해석적 ogive 반경과 비교한 값이며, 최근접 거리나 전체 표면 최대오차의 증명은 아니다.

| 설정, mm | 절점 / 삼각형 | 최대 AR / 최소각 | 중심 반경 편차 최대 | 현재 검사 |
|---|---:|---:|---:|---|
| D2/L3, target 10, 곡률 off | 9 / 10 | 1.7905 / 29.47° | 0.3772 mm | 통과 |
| D50/L100, target 10, 곡률 off | 147 / 276 | 2.1016 / 30.72° | 1.5201 mm | 통과 |

D50/L100 절점은 해석적 원호 식을 약 2.84e-14 mm 잔차로 만족했고, mesh bbox는 x,y=±25, z=0..100 mm였다. 원호 기반 CAD 구성 자체가 전면적으로 잘못됐다는 증거는 발견하지 못했다. 그러나 절점이 CAD 위에 있는 것과 삼각형 면이 곡면을 충분히 근사하는 것은 다르다.

기존 ordinary 경로는 `MeshSizeFromCurvature`를 설정했다. 현행은 이를 0으로 두고 선택적인 Python curvature callback으로 대체한다. 기본 plate 설정에서 geometry만 ogive로 바꾸면 곡률 보정이 자동 활성화되지 않는다. 면적/체적 오차도 계산되지만 처음 생성한 mesh에 대한 일반 허용오차 gate로 쓰이지 않는다. AR·최소각·양의 ICN만으로 곡면 재현성을 보장할 수 없다.

참고 실험으로 현재 D50/L100 CAD와 target 10을 유지하고 기존 ordinary의 기본 곡률 분할 50, point/boundary 확장, smoothing=3 옵션을 적용했을 때 163절점/308삼각형, 중심 반경 편차 1.2281 mm였다. 이는 일부 옵션만 바꾼 격리 실험이다. 구버전 전체 실행 결과가 아니며, 구버전 옵션 복원만으로 엄격한 0.01 mm 요구를 해결한다는 증거도 아니다.

### D. 생성 후 화면 표시 완료가 구현·검증 계약에 없다

`native_ui.launch()`는 model이 없는 상태에서 FLTK를 초기화한다. 생성 후에는 ONELAB 상태와 `fltk.update()`를 갱신하지만, 새 mesh를 대상으로 한 명시적인 `graphics.draw()`, 화면 맞춤, surface edges/faces 표시 정책이 없다. `fltk.update()`는 UI widget/view 갱신 API이며 그 자체가 새 형상에 대한 camera fit 계약은 아니다.

이는 첨부 화면의 확대된 CAD 선과 잘 맞는 원인 후보다. 실제 사용자 창에서 카메라·visibility를 각각 변경한 비교 시험은 수행하지 않았으므로 단일 원인으로 확정하지 않는다. 기존 flicker 수정과 별개로 생성 완료 표시 처리가 필요하다.

현재 `tools/native_ui_smoke.py`도 실제 FLTK lifecycle과 API로 주입한 Action, NAS 생성만 검사하며 widget 배치·마우스 조작·mesh가 화면에 들어오는지는 검사하지 않는다고 명시한다.

### E. 파일 저장 성공과 현재 ogive 결과 식별이 혼동된다

`outputs/run_bb79fd1899ff4aa9a54a9b42f65f7f3f/mesh.nas`를 pyNastran으로 다시 읽으면 80절점/156요소, bbox [0,0,0]..[2,2,2]다. 이 파일은 D50/L100 ogive가 아니라 cube 결과에 해당한다. 최신 NAS가 존재한다는 사실은 방금 요청한 ogive가 성공했다는 증거가 아니다.

현재 실패는 새 NAS를 발행하지 않으며 기존 run 폴더는 유지한다. UUID 폴더와 공통 `mesh.nas` 이름만으로는 사용자가 해당 결과의 형상과 실행을 구별하기 어렵다. 파일 독립 읽기는 저장 무결성을 검사하지만 요청 형상의 적절한 해상도까지 검증하지 않는다.

## 3. 기존 방식과 Plugin/API의 역할 정리

| 기능 | 현재 상태 | 수정 원칙 |
|---|---|---|
| ogive 원호·반회전·접합 | 기존 방식 유지 | 해석식, tip/base, t>0 내부면·바닥 annulus까지 검증하고 유지 |
| 전역 크기·파장·국소 field | native field 사용, 기본값·선택 정책 변경 | 기존 baseline과 차이를 명시하고 원하는 효과를 유지하는 단일 planner로 정리 |
| mesh algorithm | 기존 field 적용 시 5, 현행 항상 6 | 동일 CAD/field에서 알고리즘 차이의 품질·시간을 검증해 선택 정책 확정 |
| 곡률 제어 | 선택적 Python callback·투영·face 재분할 | native 곡률/field를 초기 생성에 활용하고, 꼭 필요한 오차 제어만 별도 유지 |
| 요소 품질 | AnalyseMeshQuality ICN 채택 | 단일 adapter 유지. AR≤3/최소각≥20°를 임의 ICN 하한으로 치환하지 않음 |
| CAD 편차 | 자체 CAD API 측정 | DiscretizationError의 결과 대응·투영 실패 처리·trim을 비교해 대체 가능 범위 결정 |
| 절점 개선 | Relocate2D/Laplace2D | native optimize 유지. Plugin Smooth는 view 값 평균이므로 대체 수단이 아님 |
| topology·경계·법선·rollback | 제품 전용 검사 | 직접 대응하는 검증 기능이 없는 부분만 유지하고 중복 호출 정리 |
| NAS | 독립 pyNastran 대조 후 발행 | 좌표/ID/connectivity/PID 대조와 원자적 발행 유지 |

Distance/Threshold/Box/Min은 Gmsh size field이고 OCC/optimize는 API다. 모두를 Plugin이라고 부르거나 Plugin 사용량 자체를 목표로 삼지 않는다. 동일 기능 대체가 검증되면 이전 구현을 제거하고, 이중 계산 경로나 조용한 fallback을 남기지 않는다.

DiscretizationError를 현재 채택하지 않은 근거도 존재한다. 고정 4.15.2 source는 list-based 표본 출력을 만들며 원본 element ID 및 closest-point 성공을 adapter가 바로 검증할 수 있는 계약을 제공하지 않는다. 따라서 단순 교체를 약속하지 않는다. 자체 구현이 필요하다면 역할을 최소화하고 독립 검증을 확보한다.

근거: [Gmsh 공식 매뉴얼](https://gmsh.info/doc/texinfo/), [검토한 4.15.2 source](https://gmsh.info/src/gmsh-4.15.2-source.tgz), 현행 `docs/validation-ko.md`의 API 선택 근거. 소스의 `gmsh.cpp`, `DiscretizationError.cpp`, 프로젝트 `quality.py`를 대조했다.

## 4. 수정 순서와 완료 기준

### 1단계 — 재현 기준과 생성 입력 계약 고정

- 사용자가 실제로 사용하는 D50/L100/t0, target 10 mm를 필수 acceptance case로 추가한다.
- 곡률 off, 절대오차 단독, 상대오차 단독, 둘 다, 최소 크기 on/off를 분리한다. t>0 및 단위 mm→m도 포함한다.
- shape 변경 시 기존 target과 곡률 off를 그대로 물려받는 동작을 정리한다. 곡면용 기본 곡률 제어와 명시적 해제의 의미를 구분한다. 기준 크기와 실제 편차를 함께 검증해 기본값을 정한다.
- Widths 지원 여부를 생성 전에 설명·검사한다. 미지원 선택을 조용히 무시하지 않는다.
- 합격 기준: 잘못된 조합은 기존 결과를 지우기 전에 원인·조정 항목을 표시하고, 유효한 기본 설정은 지원 형상을 생성한다.

### 2단계 — ogive 곡률·해상도 제어 수정

- D/L/t 해석식과 OCC 표면, mesh 절점, 삼각형 내부 표본을 각각 검증한다. apex/base/seam의 투영과 곡률 질의를 따로 추적한다.
- 초기 생성 크기와 사후 허용오차 판정을 분리한다. 초기 곡률 추정 하나를 실제 필요 요소 크기로 단정하지 않는다.
- 위반 위치 주변의 native field 보강을 우선 검토한다. face 전체와 모든 인접 curve를 반복 축소해 끝점의 불필요한 극소 크기를 만드는지 확인하고 수정한다.
- DiscretizationError 대체 가능성은 위 표의 계약 검증 후 결정한다. 현재 측정 결과와 독립적인 해석 ogive 표본을 기준으로 판정을 비교한다.
- 합격 기준: D50/L100의 지정 δ를 독립 표본에서도 충족하거나, 실제 미충족 위치와 최소 크기 충돌 이유를 정확히 제시한다. 단순히 최소 크기를 낮추거나 δ를 느슨하게 하여 완료 처리하지 않는다.
- 허용오차를 줄였을 때 측정 기하 오차가 개선되는지 확인한다. 전체 요소 수의 단조 증가만을 정확성 기준으로 삼지 않는다.

### 3단계 — 생성·표시·발행 상태를 일치시키기

- 실행 전 검사 → 생성 → 필요한 검사/개선 → mesh 표시 → 요청한 경우 NAS 발행의 상태를 명시한다. 생성 실패, 검사 차단, 발행 실패를 구별한다.
- 생성한 mesh에 surface edges/faces 표시를 설정하고 graphics draw를 수행한다. 새 형상 생성 시 bbox에 맞추고, idle 또는 단순 상태 변경 때는 카메라를 유지한다.
- 모델 교체가 실패했을 때의 이전 결과 보존/복구 방식을 정한다. 이전 결과가 최신 결과처럼 보이지 않게 한다.
- 성공 시 전체 NAS 경로와 해당 형상·치수·단위를 식별 가능하게 표시한다. 한 개 NAS 출력 계약 안에서 파일 이름이나 NAS 주석을 활용하며 보고서 sidecar를 추가하지 않는다.
- 합격 기준: UI에서 생성한 mesh와 다시 읽은 NAS가 동일하고, 작은 cube→큰 ogive→작은 sphere로 바꿔도 전체 mesh가 바로 보인다. 실패하면 이번 실행 NAS가 없다는 점이 명확하다. idle flicker가 재발하지 않는다.

### 4단계 — 구조와 반복 검사 정리

- 기존 모듈을 활용해 `Geometry → SizingPlan → Generate → Inspect/Improve → Publish` 단일 흐름으로 정리한다. UI는 설정·Action·표시만 담당한다.
- 현재 0.2초 idle마다 CAD/field/경계 및 mesh snapshot을 다시 비교하는 비용을 측정한다. UI 변경 감지와 무거운 mesh 검사를 분리하되, 외부 Gmsh 편집 감지와 Action/발행 직전 최신 검증은 보존한다.
- 개선 전후·발행 시 같은 revision의 검사를 중복 실행하는 부분을 정리한다. 좌표 변경 시에는 검사 결과를 재사용하지 않는다.
- 개선은 요소 연결을 보존하는 절점 이동이므로, 조밀도 부족을 개선 pass 증가로 해결하려 하지 않는다.
- 합격 기준: 같은 입력·session 상태에 대해 UI/CLI 결과가 일치하고, stale mesh·field 변경·rollback 실패를 여전히 차단한다. 불필요한 별도 controller나 새 fallback 계층을 추가하지 않는다.

### 5단계 — 실제 사용 기준으로 검증·문서 갱신

- native: plate, sphere, cube, cylinder, dihedral, ogive t0/t>0 전체.
- CAD: 단순 평면/곡면과 복잡한 fillet BREP. 실제 좌표·connectivity·PID·단위·법선을 비교한다.
- UI: 첫 생성, 크기가 다른 형상으로 전환, 연속 생성, 실패 후 재생성, NAS 경로 확인, 초기 화면 맞춤과 idle 안정성.
- NAS: 현재 mesh와 독립 reader의 좌표/ID/connectivity/PID 대조, 실패 시 새 파일 없음, 이전 결과를 최신으로 오인하지 않는 표시.
- 기존/새 버전 비교는 동일한 CAD·단위·effective size·곡률 요구·Gmsh 버전을 맞춘 개발 시험으로 수행한다. 제품에 비교 모드를 다시 추가하지 않는다.
- guide에는 각 형상의 기준점·축·D/L/t 및 크기·곡률 옵션의 적용 결과를 그림과 예제로 함께 설명한다. 특히 ogive t0는 열린 base를 가진 sheet라는 점을 명시한다.
- 전체 회귀 테스트와 실제 화면 검증을 모두 마친 뒤에만 수정 완료로 판단한다. 기하 및 저장 검증을 EM/RCS 정확도 보장으로 표현하지 않는다.

## 5. 이번 검토의 한계와 후속 전달

이번에는 현행 코드, 기존 설계·소스, 저장된 NAS, 독립 생성 실험을 확인했다. 구버전 전체 runtime과의 동조건 end-to-end 비교 및 사용자 창의 camera/visibility 조작 시험은 아직 수행하지 않았다. 현재 구현의 독립 기하·저장·화면 검증으로 보완하며, 구버전 전체 실행과 동등하다는 주장은 하지 않는다.

검토 단계에서는 계획서만 작성했고, 후속 요청에 따라 실행 코드와 검증을 갱신한다. 구현 및 merge 단계에서는 사용자가 지정한 저장소에 검증된 변경을 한 묶음으로 전달하고, merge 요청 범위에 따라 병합 후 해당 작업 branch를 삭제한다.


## 6. 구현 결정과 검증 결과

- Ogive 원호와 반회전 CAD 구성은 유지했다. 실패 원인은 허용오차를 이미 반영한 pole의 유한 해상도에 face 축소 배율을 다시 곱하던 동작이었다. 재생성은 `δ + (h−δ)×scale`로 유한 해상도 위의 길이를 줄이며, 통과한 모든 인접 curve에 별도 축소 배율을 전파하지 않는다. 최종 표본 검증과 실제 minimum_size 충돌 검사는 유지한다.
- Native Box/Min을 이용한 위반 영역 보강을 시험했으나 다른 곡면에서 과도한 세분화와 수렴 실패가 발생해 채택하지 않았다. 기존 field planner·callback 한 경로로 정리했다. `DiscretizationError`와 `Smooth`의 계약 차이도 여전하므로 무리하게 대체하지 않는다.
- 동일 현재 CAD/field에서 Algorithm 5/6을 대조했다. 폭 제어 판은 둘 다 통과했다. D2/L3 ogive(δ=.02)는 5에서 최소각 16.6604°·2개 shape 위반, 6에서 최소각 26.4020°·위반 0이었다. 따라서 현재 Algorithm 6을 유지한다. 이 격리 시험은 구버전 전체 파이프라인 비교가 아니다.
- 곡면 형상으로 전환할 때 곡률 제어가 꺼져 있으면 상대 허용오차 .001을 제안 기본값으로 켜며, 사용자가 이후 직접 끌 수 있다. Native 곡면의 Widths 요청은 model을 지우기 전에 명확히 거부한다.
- 생성 시 surface edges/faces를 표시하고 bbox·viewport에 맞춰 oblique view를 한 번 적용한다. Idle에서는 카메라를 변경하거나 무거운 CAD/mesh 검사를 반복하지 않는다. Action과 발행 직전의 현재 CAD·field·경계·mesh 검증은 유지한다.
- 동일 CAD 및 메쉬의 검증된 편차만 재사용한다. 캐시 키는 CAD fingerprint와 절점/요소 ID·좌표·연결·surface·1D 경계 요소를 포함한다. 나머지 품질·topology·법선·NAS 검사는 계속 실행한다.
- 성공 출력 폴더에 형상·치수를 넣고 NAS 주석에 입력 형상과 단위를 기록한다. 실패 시 이번 실행에 NAS가 없음을 표시한다. 보고서 sidecar는 만들지 않는다.
- 사용자 추가 요청에 따라 Resources 모듈·UI·schema와 국소/공간/투영 작업량 중단 조건을 삭제했다. 표본 수 100 및 반복 횟수 입력 10의 고정 상한, 엔진의 강제 단일-thread 설정도 제거했다. Native Gmsh thread 설정을 덮어쓰지 않는다. 사용자가 지정하는 개선/곡률 재생성 횟수와 수학적으로 유효한 입력 검사는 유지한다.
- D50/L100/t0, target 10, minimum .01, 절대 δ=.01의 검증: 33,375절점·66,536삼각형. 독립 10/19/37 표본의 편차는 .00755071/.00757532/.00759446 mm였다. 최대 AR 2.47228, 최소각 23.9532°. 독립 NAS 읽기·좌표/ID/connectivity/PID 대조까지 통과했다.
- 실제 FLTK에서 cube→D50/L100 ogive→sphere→179° dihedral로 전환하며 잘못된 확대/이동 상태를 의도적으로 주고 매번 전체 mesh가 화면에 들어옴을 확인했다. 이 화면 시험은 framing을 분리하기 위해 곡률 OFF로 실행했다. 조밀도 acceptance는 별도의 위 D50/L100 시험이다.

최신 전체 회귀 결과와 재현 명령은 [개발 검증 기록](validation-ko.md)에 모은다. 검증용 JSON·PNG·log는 `.cache/reassessment`에만 둔다. 사용자가 확인할 검증된 ogive NAS 한 파일은 `outputs/run_ogive_diameter50_length100_thickness0_a1607459b3844a839b3c10464bb3bde0/mesh.nas`로 복사하고 원본과 SHA256이 같음을 확인했다. Git에는 실행 산출물을 게시하지 않는다.
