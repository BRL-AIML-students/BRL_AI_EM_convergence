# 5단계: 편차 기반 곡률·자원 검사

검증일: 2026-10-19. 작업 branch: `codex/rebuild-core`. 시작 commit: `ddf942c`. 원격 push·PR·merge·branch 삭제 없이 이 새 프로젝트에서 구현·실행했다. 1–4단계 기록은 당시 상태로 보존한다.

## 구현과 선택 근거

- `mesh.curvature`의 절대 편차/국소 특징 상대 편차, 재생성 횟수, 생성/최종 표본 수를 strict schema와 ONELAB에 연결했다. 상대 편차의 특징 길이는 face의 `sqrt(area)`, curve의 arc length이며 두 편차가 있으면 작은 값을 사용한다. 전체 bbox D를 사용하지 않는다.
- CAD curve 곡률 및 surface 최대 절대 주곡률에서 초기 요청을 계산하고, Gmsh `setSizeCallback`에서 기존 field 결과와 Min으로 적용한다. 전역 `MeshSizeFromCurvature=0`이며 기존 200 clamp를 옮기지 않았다. `CurvatureRequest`는 초기 required·feedback applied·원당 필요 분할 수를 자원 설정과 별도로 보관한다.
- 실제 triangle 내부/edge·boundary line의 표본을 원본 element ID에 대응시키고 CAD projection 거리로 재생성을 결정한다. 초과한 CAD entity별 배율과 해당 face의 경계 요청을 낮춘다. 한 face 전체를 보수적으로 세분화할 수 있으며 재생성 후 새 mesh를 검사한다. 이전 numpy snapshot은 다음 생성 전에 해제한다.
- `sampling_nodes=10`은 triangle당 55개, 최종 기본 `verification_nodes=19`는 190개 barycentric 표본이다. 생성 종료·개선 전후·발행 시 현재 mesh를 새로 측정한다. 최대 편차 비율이 커진 relocation은 수용하지 않는다. CAD/설정/기존 field·경계의 생성 참조와 단위/PID 검사도 유지한다.
- Projection 좌표·parameter·재구성 값의 대응과 유한성, surface trim 포함을 확인한다. 원본 ID 대응 누락·projection/trim 실패·반복/하한/자원 충돌은 성공으로 바꾸지 않는다. 편차 view·`.pos`·`.msh`·보고서·log 파일은 생성하지 않는다.

### `DiscretizationError`를 채택하지 않은 이유

[공식 4.15.2 source archive](https://gmsh.info/src/gmsh-4.15.2-source.tgz)의 `src/plugin/DiscretizationError.cpp`를 직접 확인했다. 압축 파일 SHA256은 `be3f66f225d27ba9fa014f07e83169285da8a051b0e8ab7103d88066b39bdd3e`다. Plugin은 supersampling 후 거리값이 있는 list-based 소삼각형을 만들며 원본 element ID를 출력하지 않고 `closestPoint` 성공 상태도 검사하지 않는다. 따라서 이번에는 원본 ID 및 trim/projection 계약을 직접 확인하는 CAD API 측정을 선택했다. Plugin 실패 후 fallback하는 구조가 아니며, 측정값은 실제 재생성/발행 판정에서 소비한다.

같은 source의 `src/common/gmsh.cpp`와 `src/geo/OCCFace.cpp`에서 극점의 `IsCurvatureDefined()` 실패 시 출력 curvature를 설정하지 않는 경로와 API wrapper가 그 반환 상태를 사용하지 않는 동작을 확인했다. 실제 sphere pole에서도 작은 미정 값과 zero direction이 반환됐다. 주곡률 방향을 확인하고 parameter domain 안쪽 `1e-5` 비율 지점에서 다시 구하며, 유효한 결과를 못 얻으면 차단한다. 이 인접점 값은 초기 추정일 뿐 최종 편차 검사를 대신하지 않는다.

또한 기본 `getBoundary(..., combined=True)`는 한 surface에서 반복되는 seam을 상쇄한다. 곡률 생성 제어에는 `combined=False`로 seam을 포함했고, OCC sphere pole의 경계 없는 null curve와 round-off mass는 실제 seam과 구별했다. curve closest-point parameter의 DLL 문제는 4단계와 같이 유효 좌표에서 parameter를 재구성한다.

## 자원 검사의 정확한 범위

`resources` 기본값은 전체 model node 150000, triangle 200000, 실행 프로세스 memory 2048 MiB, Action 작업 시간 300 s, 편차 projection 누계 20000000이다. CLI 전체 실행 또는 하나의 ONELAB Action이 공통 예산을 사용한다. 다음 Action은 새 예산이며 UI idle 시간을 포함하지 않는다. CLI 부모는 Gmsh 코어 import를 지연하고 worker가 실행 코어를 읽는다.

Windows에서 `GetProcessMemoryInfo`의 private committed bytes를 검사한다. node/triangle 수는 생성 후 및 검사/발행 시 현재 Gmsh model에서 읽는다. 시간·메모리는 API 호출 전후, 곡률 callback, 표본 batch의 **협력적 검사**이며 단일 OCC/Gmsh 호출의 강제 중단이나 allocator hard cap이 아니다. 일시적인 peak·엄격한 종료 시각을 보장하지 않는다. Linux RSS 경로는 구현했으나 이번 검증 플랫폼은 Windows다.

최소 크기·좌표 정밀도·반복·측정·요소 수·시간·메모리 한도와 요구가 충돌하면 한도를 늘리거나 요구를 완화해 성공 처리하지 않는다. NAS 독립 읽기 후에도 commit 직전에 다시 검사하고, 실패하면 이번 pending 폴더만 정리한다. 이전 정상 NAS는 보존한다.

## 검증

환경은 Python 3.12.14·Gmsh 4.15.2·NumPy 1.26.4·pyNastran 1.4.1·pytest 8.4.2다. `uv.lock`과 Gmsh DLL은 4단계에서 바꾸지 않았다. 고정 DLL SHA256은 `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage5-full
```

전체 **277개 통과, 210.03 s**, warning 없음. 이전 240개와 이번 37개를 포함한다. 이후 이전 snapshot의 조기 해제 및 현재 CAD 위 node 이동 사례의 발행 차단을 강화하고, 해당 feedback/현재 mesh 테스트 **6개 통과, 26.49 s**를 확인했다.

| 검증 | 확인한 결과 |
|---|---|
| sphere·disk·cylinder·작은 fillet·ogive tip | 실제 CAD 곡률·표본 편차·단위·법선/topology 검사, 필요한 재생성 |
| R=10·100 mm, delta=0.001 mm | 초기 필요 분할 각각 223·703; 실제 R=10 원 경계 line 223개 |
| 서로 다른 sphere와 translation | 국소 반경/면적별 다른 목표; 멀리 떨어뜨려 bbox를 키워도 같은 국소 목표 |
| 평면/곡률 OFF | 평면의 곡률 조건이 불필요한 세분화를 추가하지 않음; 기존 plate NAS 바이트 유지 |
| null pole·미정 주곡률·callback 오류 | 미정 값 소비 방지, callback 정리, 정상 NAS 미발행 |
| projection NaN·trim 밖·반복 0·minimum_size 충돌 | 실패/미완료를 성공으로 처리하지 않고 발행 차단 |
| 현재 CAD 위에서 cylinder node 이동 | node는 CAD 위에 있으나 triangle 편차 비율 1.80966; `cad_deviation`으로 발행 차단 |
| node/triangle·메모리·시간·누적 표본 한도 | 실제 mesh/Windows memory API와 제어된 clock 검증, nested budget 공유/다음 Action 초기화 |
| NAS 독립 읽기 뒤 resource 실패 | pending만 정리, 이전 정상 NAS 내용·경로 보존 |
| ONELAB controls | CLI schema round-trip, 변경 시 scene 무효화, 자원 초과 Action 차단 |
| 실제 CLI·FLTK | 새 cylinder NAS 발행, 정확한 바이트 일치·FLTK 종료/finalize |

### 곡면·표본 수 검증 값

개발용 native OCC fixture를 BREP로 저장해 새 importer로 읽었다. 보관 runtime/env를 실행하지 않았고 STEP 중간 변환을 사용하지 않았다. ogive는 D=2·L=3 mm의 정확한 원호를 두 번 반회전하고 fragment한 열린 sheet다. primitive를 직접 선택하는 제품 입력은 아직 plate이며 ogive D/L/t 입력은 6단계다.

| CAD·설정 (mm) | 최종 node/triangle | 생성 이력: triangle, 표본/허용 편차 비율 | 최종 10 / 19 / 37 표본 비율 |
|---|---|---|---|
| cylinder R=1·H=2, cap=.7, delta=.02 | 171 / 338 | 338, .894208 | .883069 / .894208 / .894208 |
| circle R=10, cap=1, delta=.001 | 647 / 1069 | 1069, .992323 | .980071 / .992323 / .992323 |
| sphere R=1, cap=.7, delta=.02 | 421 / 838 | 266, 2.031275 → 838, .662228 | .653999 / .662228 / .662228 |
| fillet R=.15, cap=.7, delta=.01 | 1257 / 2510 | 2190, 1.806250 → 2510, .984028 | .971459 / .984028 / .984028 |
| ogive D=2·L=3, cap=.7, delta=.02 | 426 / 824 | 458, 1.124768 → 653, 1.309438 → 824, .712727 | .704079 / .712727 / .712727 |

원의 chord 중점에서는 독립적인 정확한 sagitta로도 delta 이하를 확인했다. sphere는 각 flat triangle에서 원점으로의 최소 거리(면 내부와 세 edge의 projection)를 이용해 연속 최대 radial deviation을 별도로 계산했고, `0.013244568771413445 mm < 0.02 mm`를 확인했다.

위 값은 Gmsh build·입력·설정을 고정한 이번 사례의 결과이며 일반 CAD의 연속 최대 거리나 EM 수렴 증명이 아니다. 표의 19/37 일치도 모든 CAD에 대한 보증이 아니다.

fillet의 cap=.7은 편차를 만족하지만 형상 위반 39개·최소각 13.496°였다. 편차만으로 발행을 허용하지 않는다. 요구를 완화하지 않고 cap=.15·delta=.01을 적용하면 2120 node / 4236 triangle, 재생성 1회, 최소각 21.3935°·형상 위반 0, 편차 비율 .984028, relocation 없이 독립 NAS 검증·발행을 통과했다. cap은 전역 요청 길이이므로 작게 하면 요소 수도 늘어난다. 6단계에서는 복잡 CAD에 필요한 설정과 적용 범위를 계속 검증한다.

## 실제 NAS와 재현성

- `outputs/run_37671de3c7d54b7eb200d63db8a5e390/mesh.nas`: cylinder 171 node / 338 triangle, PID 1–3, SHA256 `2f40427116253467aaf853022433dc088ef5af569e3e7e619b770268a6c9dfbb`.
- `outputs/run_fa8414e60d294b32a544c14df1ff9e89/mesh.nas`: circle 647 node / 1069 triangle, PID 1, SHA256 `d414ebc4a2d4f4614e79dcf285f038bce25c20d3b4e160939cc858c18ce32d54`.
- `.cache/native-smoke/fd125b3dba05421ea0defdead47f66ea/run_863c6a2a2181499692002fabb97c2601/mesh.nas`: 실제 FLTK에서 Action을 API로 주입해 같은 cylinder를 발행했다. CLI와 전체 bytes가 일치하여 좌표·ID·connectivity·PID까지 일치했다. widget 외관이나 마우스 조작의 시각 QA는 아니다.
- `outputs/run_fe83b04413bb4fdc8be059b973cc1bc2/mesh.nas`: plate 91 node / 148 triangle, SHA256 `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`. 1–4단계와 같은 bytes다.

위 run 폴더는 각각 `mesh.nas` 한 건만 포함한다. 개발 fixture·probe·source archive는 ignored 로컬 `.cache`에 두고 제품 출력에 복사하지 않았다.

## 남은 작업과 한계

6단계의 추가 native primitive(특히 ogive D/L/t), 단순/복잡 CAD의 전체 경로 통합, 최종 사용 문서·수동 UI 확인, GitHub 대상 결정이 남았다. 시간/메모리의 강제 native 중단은 구현하지 않았다. 필요하면 프로세스 분리와 native UI의 현재 mesh 보존 계약을 함께 설계할 대상이며 이번 협력적 검사로 구현했다고 표현하지 않는다.

기하 편차·요소 형상·NAS 읽기 검증은 MoM/RCS 정확도 증명이 아니다. 현재의 one-way 유한 표본과 topology/교차 검사의 범위를 넘는 Hausdorff, 전체 face/face 교차, 전자기 결과 수렴은 보증하지 않는다.

참고: [Gmsh CAD principal-curvature API](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002fgetPrincipalCurvatures), [mesh size callback](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002fmesh_002fsetSizeCallback), [DiscretizationError](https://gmsh.info/doc/texinfo/gmsh.html#Plugin_0028DiscretizationError_0029).
