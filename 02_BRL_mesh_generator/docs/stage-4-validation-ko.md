# 4단계 특징별 크기장·폭/간극·전이 구현 및 검증

검증일: 2026-10-19. 작업 루트: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`. 기준 commit: `4a6c94f`. 구현·예제·검증 기록을 로컬 `codex/rebuild-core`에 함께 보존하며 GitHub push·PR·merge·branch 삭제는 최종 사용자 지시 단계까지 보류한다.

## 변경과 책임

- `schema.py`: 숫자/bool/object/정수의 공통 엄격 검사.
- `sizing_config.py`: 사용자가 요청한 전역·국소 조건의 불변 구조와 JSON parser. CAD 측정이나 실제 적용값을 입력 구조에 섞지 않는다.
- `features.py`: CAD edge 길이·지원 범위의 실제 면 폭·분리 CAD 최소 거리와 적용 영역을 측정한다. 측정 실패·미지원·한도 도달은 성공 처리하지 않는다.
- `sizing.py`: 전역 목표 결정, 특징별 독립 목표와 유지/전이 계산, Gmsh native field 적용·변경 감시, 개선에서 소비하는 국소 크기 감사.
- 기존 `engine`/`inspection`/`improvement`와 ONELAB을 같은 코어에 연결했다. 이전 설정·Action을 위한 호환 alias나 scoring·보고서·독립 진단 view를 추가하지 않았다.

## 전역 크기와 단위

`mesh.target_size`가 있으면 명시 상한, `mesh.wave`가 있으면 균질·무손실 매질의 파장 기반 요청으로 해석하고 최솟값을 적용한다. 둘 다 없을 때만 surface CAD bbox union의 대각 길이 × `fallback_fraction`(기본 0.1)을 사용한다. NAS에 쓰지 않는 독립 curve/point의 먼 위치를 fallback 형상 크기에 넣지 않는다. 이 구현에서 fallback은 명시 조건이 있을 때 추가로 크기를 지배하는 cap이 아니다.

파장 길이는 `c0 / frequency_hz / sqrt(relative_permittivity) / sqrt(relative_permeability) / elements_per_wavelength`를 `output_unit`으로 변환한다. 단일 양의 주파수와 양의 실수 물성만 받으며 손실·분산·대역 모델로 임의 확대하지 않는다. 파장당 요청 개수는 EM 정확도 기준이 아니다.

`target_size` 생략이 자동 선택이며 0·null·bool·비유한 값은 허용하지 않는다. 전역 cap·최소 크기 하한·수동 크기·Box 좌표·유지/전이 거리는 출력 단위다. 자동 특징은 변환된 CAD에서 측정한다. STEP/IGES의 내장 단위와 BREP의 단일 변환 경로를 그대로 유지했다.

## 특징별 적용 범위

| 특징 | 측정·요청 | native 적용 |
|---|---|---|
| 짧은 edge | 해당 curve의 OCC 길이 / divisions; seam·길이 0 pole을 자동 짧은 edge에서 제외 | Distance → Threshold |
| 면 폭 | 단일 loop·직선 경계·볼록 평면 polygon의 최소 지지선 폭 / divisions | 해당 면/경계의 상수 Restrict + 경계 Distance → Threshold |
| 분리 간극 | 다른 CAD 연결 성분·같은 solid가 아닌 face 쌍의 bbox 후보 이후 실제 occ.getDistance / divisions | overlap extent와 최단 connector를 포함하는 보수적 Box |
| 수동 curve | 실제 curve tag와 명시 size | Distance → Threshold |
| 수동 Box | 출력 단위의 bbox와 명시 size | Box |

특징마다 자기 길이로 목표를 계산하며 전체 최소 특징 하나를 모두에게 복사하지 않는다. 전역 cap과 모든 leaf field를 Min으로 결합한다. 영향 영역이 겹치면 더 작은 요청이 적용된다.

폭은 회전한 10×0.6 평면에서도 0.6을 구하며 √면적이나 축 방향 bbox 폭을 쓰지 않는다. 곡면·곡선 경계·hole·비볼록 neck/접힘의 일반 국소 폭은 미지원이다. 요청하면 `width_unsupported`로 차단하고 면 선택 또는 수동 영역을 사용하도록 한다. 모든 CAD의 일반 local feature size를 측정했다고 표현하지 않는다.

공유 경계 또는 같은 연결 성분/solid 내부의 면을 gap으로 취급하지 않는다. 연결된 CAD만 있을 때 불필요한 gap pair 예산도 소비하지 않는다. 분리 entity의 거리 0·접촉·음수/비유한/실패한 CAD 거리는 차단하며 근접 좌표를 병합하지 않는다. 같은 face의 자기 근접은 이 gap 규칙의 지원 범위가 아니다. 보수적 Box는 임의 곡면 전체에서 동일한 gap 폭이 있다는 의미가 아니며 과도한 국소 세분화 가능성은 전체 자원 검증과 구분한다. gap/divisions는 표면 목표 길이이고 빈 공간에 만드는 체적 요소 층 수가 아니다.

## 유지·전이·sampling·하한

- 유지 거리 r은 생략 시 해당 국소 목표 h이며 명시 0도 허용한다. 전이 거리 t를 생략하면 `(h_global-h)/growth_rate`, 기본 slope는 0.3이다. `DistMin=r`, `DistMax=r+t`. Box는 r만큼 확장하고 바깥 Thickness=t를 적용한다.
- 전역 3·국소 0.2·유지 0.4·slope 0.3이면 t≈9.333, DistMax≈9.733이다. 이 slope는 실제 인접 요소의 √면적 비율 또는 EM 정확도를 보장하지 않는다.
- Distance 표본 수는 curve 길이와 `sampling_fraction × min(h, 양의 유지 거리, t)`를 기준으로 정하고 parameter 표본의 chord 간격·전체 길이 근사를 확인한다. 표본 부족 시 늘리며 한도에서 조용히 clamp하지 않는다. 기본 fraction=0.25, max_sampling=4096이다.
- CAD 쌍/폭 연산은 max_pair_tests=10000, 적용 특징은 max_features=4096이 기본이다. 폭의 예산은 SVD/쌍 배열 계산 전에 확인하고 thin SVD를 사용한다.
- `minimum_size`가 전역 또는 필수 국소 요청보다 크면 `minimum_size_conflict`로 meshing 전에 차단한다. 하한이 없으면 실제 요청 목표의 최솟값을 MeshSizeMin으로, 전역을 MeshSizeMax로 적용한다. 값이 있을 때도 필수 요청을 조용히 완화하지 않는다.
- MeshSizeMin/Max는 요청 field를 제한하며 모든 실제 edge의 엄격한 상·하한이 아니다. 측정·field 감사 한도와 전체 meshing 시간·메모리·요소 수 한도는 구분한다. 후자는 5단계에 남아 있다.

## 적용 상태와 개선

Scene에 실제 전역/최소 요청, 지배 후보, 특징별 길이·목표·유지·전이·Sampling, field ID/type/옵션/목록을 보존한다. Distance의 빈 SurfacesList 및 Restrict의 비선택 차원 목록·IncludeEmbedded 같은 기본값도 명시하여 감시한다. field 추가·삭제·계수·목록·지정 전역 크기 옵션 변경 시 재생성을 요구한다. API 오류에서 전역 균일 mesh로 fallback하지 않는다.

공개 Python field API에는 background 선택의 getter가 없다. 따라서 생성 시 Min을 실제 setter에 전달한 것을 확인하고 실제 공간별 요소와 native/CLI NAS를 검증했다. 이 검증을 임의 외부 script가 background 선택만 바꾼 모든 경우의 감지 보증으로 확대하지 않는다. BRL 밖에서 field/mesh 생성 경로를 변경했으면 BRL Generate 경로로 다시 생성한다.

개선 비악화 조건에 `실제 edge 길이 / edge 중점의 CAD 거리 기반 국소 요청`의 최댓값을 추가했다. 이것은 연속 CAD 거리 설계에 대한 감사이며 Gmsh의 표본 Distance evaluator와 같은 수치라고 가정하지 않는다. 중점 표본만으로 edge 전체의 엄격한 목표 충족을 보증하지 않는다. 감사 실패는 미완료로 차단한다.

이 build에서 `getClosestPoint(1)`은 올바른 projection 좌표와 함께 잘못된 parameter 출력을 반환하는 사례가 있었다. 그 parameter를 소비하지 않고 projection 좌표의 `getParametrization`을 명시적으로 다시 구한다. NaN parameter 주입·정상 좌표 사례에서도 예상 연속 요청 길이를 확인했다. 실패를 다른 의미의 API 결과로 조용히 대체하는 경로는 없다.

실제 local Box가 있는 판을 변형한 후 Relocate2D를 실행했다. 형상 위반 2 → 0, 국소 최대 edge 비율 1.8768371877 → 1.2965845530으로 줄었고 구조/field를 유지했다. 후보의 국소 비율이 악화되면 다른 보존 지표와 함께 거부·정확한 좌표 rollback을 수행한다. AR ≤ 3·최소각 ≥ 20°·Plugin ICN 정책과 별도 topology/법선/NAS 검사는 유지했다.

## CLI·ONELAB 및 검증

ONELAB의 BRL/Sizing에서 cap·파장·하한을, BRL/Local에서 규칙·divisions·유지·전이·sampling을 설정한다. 사용하지 않는 제어는 숨긴다. `BRL/03 Applied global size`는 생성한 전역 요청을 출력 단위로 표시하고 재생성이 필요하면 0으로 무효화한다. 고급 entity 선택·수동 region·한도는 시작 JSON을 보존한다. 공통 schema 검증과 같은 생성·검사·개선·발행 코어를 호출한다.

최종 전체 테스트: **240 passed in 127.02s**, warning 없음.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage4-final
.\run_cli.bat examples\thin_plate.json
.\run_cli.bat examples\gaps.json
.\.venv\Scripts\python.exe -B -X utf8 -m tools.native_ui_smoke examples\thin_plate.json
.\.venv\Scripts\python.exe -B -X utf8 -m tools.native_ui_smoke examples\gaps.json
```


기존 149개 검증과 함께 엄격한 중첩 schema·자동 fallback/파장/단위·회전 폭·특징별 독립성·실제 gap Box·공유 경계/접촉·bbox false candidate·미지원 폭·하한 충돌·sampling 증가·예산 선차단·field metadata 변조·현재 mesh/필드 재검사·실제 local 개선·실패 시 이전 NAS 보존을 확인했다. STEP/IGES 내장 단위 import 후에도 폭 목표가 맞게 적용된다. 고정 조건의 local gap CAD를 두 번 생성하여 node/element ID·좌표·connectivity·PID를 포함한 NAS 전체 byte 일치를 확인했다.

반경 2의 원 경계에서 Sampling 98 → 194로 증가시켰을 때 각 21 node·28 triangle, edge 길이 중앙값 1.0352761804를 관측했다. 이는 이 사례의 표본 밀도 안정성이고 모든 curve/field/geometry 오차의 보증은 아니다.

| 최종 예제 | node / triangle | 실제 결과 |
|---|---:|---|
| 기존 100×60 mm 판, 목표 10 mm | 91 / 148 | 1–3단계와 같은 NAS byte |
| 10×0.6 mm 판, 폭 divisions=3 | 255 / 402 | 목표 0.2 mm, edge 길이 중앙값 약 0.19657 mm |
| 0.6/1.2 mm gap 두 쌍, divisions=3 | 1314 / 2380 | PID 1·2 edge 길이 중앙값 약 0.2 mm, PID 3·4 약 0.39786 mm |

각 발행 폴더에는 mesh.nas 한 파일만 있다. 새로운 두 예제는 실제 FLTK window/event loop 5회·Action 주입·발행·session finalize를 확인했고 CLI NAS와 전체 byte가 일치했다. 이 smoke는 widget 배치·폰트·마우스/키보드의 시각 검증이 아니다.

최종 NAS 예제와 SHA256:

- 판: `outputs/run_aa7a7a32bff042c990da36a988fe6a95/mesh.nas`, `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`.
- 폭: `outputs/run_a831cc1806a74465a2604f3822003918/mesh.nas`, `c93cce75fcdb1c85120d5ea7f95ac67aad9b25719961522169ee070afbf0dc11`.
- gap: `outputs/run_5bc67c25dd8845d884c3ee159aa02f79/mesh.nas`, SHA256은 `662528015265394cdcdc7179a5dd007bd10b4f7fa87641624d7ace349d05a32a`다.

환경: Python 3.12.14·Gmsh 4.15.2·NumPy 1.26.4·pyNastran 1.4.1, 기존 uv.lock 유지. Gmsh DLL SHA256은 `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`. 보관본·기존 캐시·권한·원격 저장소는 변경하지 않았다. 개발 fixture와 검사 출력은 새 로컬 프로젝트 안에만 생성했다.

## 남은 단계

5단계의 편차 기반 곡률·원당 목표 200 초과 요구·전체 생성 자원 제한, 추가 native primitive 요구와 6단계의 복잡 CAD·실제 UI 수동 확인은 남아 있다. node/edge topology 감사가 임의 face/face 교차를 모두 증명하지 않으며 이번 size field·품질·NAS 검증을 EM 정확도나 관측량 수렴으로 해석하지 않는다.

## 근거

- [Gmsh 4.15.2 mesh size fields](https://gmsh.info/doc/texinfo/gmsh.html#Specifying-mesh-element-sizes), [field 목록](https://gmsh.info/doc/texinfo/gmsh.html#Gmsh-mesh-size-fields): Distance/Threshold/Box/Restrict/Min과 요청 크기 옵션의 기능 범위.
- [OCC getDistance API](https://gmsh.info/doc/texinfo/gmsh.html#index-gmsh_002fmodel_002focc_002fgetDistance): 실제 최소 거리·endpoint·음수 실패 반환.
- [고정 tag의 Field.cpp](https://raw.githubusercontent.com/live-clones/gmsh/gmsh_4_15_2/src/mesh/Field.cpp): Distance의 표본/기존 curve mesh node 사용과 Box 전이 의미를 확인했다. 연속 감사값과 native evaluator를 구분한다.
- [재작성 계획](rebuild-plan-ko.md), [이전 통합 계획의 크기장 요구](../../99_archive/BRL_2026-10-19/docs/mesh-generator-refactor-plan-ko.md): 요구와 실제 완료 범위를 대조했다.
