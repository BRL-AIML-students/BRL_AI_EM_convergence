# 3단계 CAD·단위·PID·ONELAB 구현 및 검증

검증일: 2026-10-19. 작업 위치: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`. 기준 commit은 2단계의 `4b4ed8f`이며, 이번 변경은 로컬 `codex/rebuild-core` branch에 보존한다. GitHub 원격 연결·push·PR·merge·branch 삭제는 하지 않는다.

## 구현 범위

- `Configuration.geometry`를 plate 또는 CAD 파일의 명시적 구조로 분리했다. schema version은 1이며 알 수 없는 키·잘못된 중첩 값·없는 CAD 경로·지원하지 않는 확장자를 거부한다. JSON과 ONELAB이 같은 parser를 사용한다.
- `mesh_model`/`generate`/`Scene`을 생성·개선·발행의 공통 실행 경로로 사용한다. 이전 plate 전용 내부 API를 위한 호환 alias는 두지 않았다.
- STEP/STP·IGES/IGS·BREP를 `highestDimOnly=False`로 읽고 확장자의 대소문자와 관계없이 명시적 format을 전달한다. 혼합 BREP의 solid·독립 sheet·curve·point를 유지한다. NAS 대상은 표면 삼각형과 그 참조 node다.
- STEP/IGES는 `Geometry.OCCTargetUnit`을 import 전에 지정한다. BREP는 입력/출력 단위 비율을 `Geometry.OCCScaling`에 지정하여 전체 compound를 entity 등록 전에 변환한다. 독립 lower-dimensional root를 빠뜨리거나 volume 경계 entity를 중복 변환하지 않고 surface tag/PID도 보존한다.
- PID는 CAD surface tag와 같으며 Physical Group으로 관리한다. 재질 번호로 해석하지 않는다. CAD revision이나 Gmsh build가 달라질 때의 tag 안정성을 보장하지 않는다.
- 기대 열린 경계는 CAD curve mesh에서, 기대 연결 성분은 meshing 전 CAD surface adjacency에서 얻는다. 관측된 삼각형의 구멍을 의도한 경계로 받아들이지 않는다. surface의 삼각형이 통째로 빠져도 차단한다.
- solid는 기존 독립 outward 검사를 사용한다. sheet는 공통 `sheet_normal` 또는 면별 `sheet_normals`로 CAD parameter normal의 기준을 지정해야 한다. 면별 값이 우선한다. 음의 기준은 `mesh.setReverse`로 생성 winding에도 적용한다. 누락된 방향, 없는 면, solid 경계의 sheet 지정은 거부한다.
- 분리 쌍은 서로 다른 CAD 연결 성분의 실제 surface tag로 지정한다. `protected_gap`은 출력 단위이며 기존 topology tolerance 충돌 판정에 연결한다. 실제 gap 측정·국소 field는 4단계다.

## 생성 참조와 현재 mesh

생성 시 설정, 원본 CAD SHA256, CAD model/entity·boundary·type·bbox·point 좌표·mass/center/inertia·Physical Group/PID fingerprint와 point/curve mesh 상태를 보존한다. 이 참조가 달라지면 이전 성공 상태로 발행하지 않고 재생성을 요구한다. fingerprint는 명시된 topology/기하 정보이며 모든 가능한 CAD 변형의 수학적 동일성 증명으로 해석하지 않는다.

surface 내부 node를 수동으로 이동하는 경우 이전 mesh 결과를 폐기하고 현재 node·element·PID로 필수 검사와 Plugin ICN을 다시 계산한다. 법선 반전·형상 불량·경계 mesh 변경·설정 변경·CAD 원본 변경은 검증 없이 발행하지 않는다. 임시 NAS와 독립 pyNastran round-trip을 통과한 뒤 이번 NAS 한 건만 원자적으로 발행한다. 기존 정상 결과는 보존한다.

## Native ONELAB 연결

실행: `run_gmsh_ui.bat examples\plate.json` 또는 `python -m brl_mesh.native_ui examples/plate.json`.

| `BRL/00 Action` 선택 | 실제 동작 |
|---|---|
| `Idle` | 대기, 생성/발행 없음 |
| `Generate + publish NAS` | 생성·검사·필요한 개선·독립 NAS 검증·발행 |
| `Generate mesh` | 같은 생성/검사/개선 코어 실행, NAS 발행 보류 |
| `Improve current mesh` | 현재 mesh 재검사 후 필요할 때 제한된 개선/rollback |
| `Publish current mesh` | 현재 mesh의 필수 검사를 새로 수행하고 NAS 발행 |
| `Close` | native session 종료 |

Action은 한 번 소비한 후 `Idle`로 돌아간다. 상태와 NAS 경로만 표시하며 점수·통계 패널·진단 view·보고서를 만들지 않는다. Geometry 선택에 따라 적용 가능한 판/CAD 제어를 표시한다. 고급 면별 방향·분리 의도는 시작 JSON에서 받아 보존한다. 사용자 설정이 바뀌면 재생성을 요구하고 일반 Gmsh File/Export는 이 BRL 발행 경로를 호출하지 않는다.

ONELAB parameter 값은 typed getter로 읽는다. Gmsh 4.15.2의 JSON getter가 Windows 경로의 backslash를 escape하지 않는 사례가 있어 parameter metadata를 JSON으로 다시 읽어 계산하는 경로는 사용하지 않는다. UI loop는 main thread에서 실행하며 창 닫기 도중 재생성/재열기를 하지 않는다.

## Gmsh 4.15.2 IGES 처리

완전히 새 프로세스에서 IGES를 첫 CAD로 읽을 때, 해당 build는 unit table 초기화 전에 target unit을 설정하여 `Could not set OpenCASCADE target unit 'M'` 오류를 냈다. 공식 tag `gmsh_4_15_2`의 OCC source에서도 IGES 경로의 `setTargetUnit` 호출이 reader 생성보다 앞선다.

IGES는 임시 in-memory model에서 target unit을 비운 명시적 초기화 read를 수행하고 그 model을 제거한 뒤, 실제 model에서 지정 출력 단위로 다시 읽는다. 초기화 read의 형상·단위를 최종 생성에 사용하지 않는다. 변환 실패를 다른 단위의 성공으로 바꾸는 fallback은 없다. IGES는 이 때문에 두 번 읽으며 큰 파일의 처리 비용은 이후 통합 검증 대상이다.

OCC는 `General.Terminal=0`에서도 import 안내를 native stdout으로 쓰므로 CLI는 worker의 pipe를 capture하고 별도의 완료 marker를 검증하여 부모의 stdout/stderr에는 한 건의 상태 JSON만 내보낸다. DLL의 표준 file handle을 조작하거나 log 파일을 만들지 않는다. worker 비정상 종료·누락/잘못된 완료 상태도 정상 발행으로 표시하지 않는다.

## 검증 결과

최종 전체 테스트: **149 passed in 100.30s**, warning 없음.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage3-final
.\.venv\Scripts\python.exe -B -X utf8 -m tools.native_ui_smoke
.\.venv\Scripts\python.exe -B -X utf8 -m brl_mesh examples\plate.json
.\.venv\Scripts\python.exe -B -X utf8 -m brl_mesh examples\mixed_brep.json
```

검증 항목:

- 기존 92개 검증을 새 Scene API로 연결하여 Plugin·topology·법선·실제 Relocate2D/Laplace2D·정확한 rollback·NAS 차단 검증을 보존했다.
- STEP/STP/IGES/IGS × m/cm/mm/um 좌표 변환, BREP mixed root 한 번 변환, BREP 출력 단위 변경 후 surface tag/PID와 면별 방향 지정의 유지.
- IGES가 첫 CAD인 새 프로세스에서 네 단위의 생성 확인. 실제 CLI의 STEP/IGES/BREP NAS 좌표와 단일 상태 JSON 확인.
- 열린 sheet의 +1/-1 winding 생성과 반전 차단. 누락된 sheet 기준·잘못된 중첩 schema·source/설정/CAD/Physical Group 변경·누락 surface 및 경계 line 변경 차단.
- 한글/공백 CAD 경로 및 혼합 대소문자 확장자 import. 상대 경로를 JSON 위치 기준으로 처리.
- 동일 설정의 CLI/ONELAB NAS byte 일치, idle 중복 발행 없음, 현재 mesh 수동 변형 후 이전 결과 폐기·재검사, 실패 Action 소비와 종료.
- 실제 FLTK window 생성·5회 event pump·API로 Action 주입·NAS 발행·session finalize를 확인했다. `tools/native_ui_smoke.py`는 매번 새 로컬 검증 폴더를 사용한다. 화면 배치·글꼴·마우스/키보드 조작의 시각 검증은 수행하지 않았으며 이 검증을 standalone ONELAB 설치 검증으로 표현하지 않는다.

시험용 CAD writer는 별도 프로세스에서 실행한다. 같은 Python 프로세스에서 STEP reader 사용 후 IGES writer를 연속 실행할 때 OCC writer가 멈추는 사례가 있어, 제품의 read-only importer 검증을 시험용 writer의 전역 상태와 분리한다. fixture subprocess에는 20초 timeout을 둔다. 제품은 STEP/IGES 중간 파일을 생성하지 않는다.

| 예제 | 결과 |
|---|---|
| 100×60 mm 판, 목표 10 mm | 91 node·148 triangle·PID 1 |
| mixed BREP, mm → m, 목표 0.25 m | 149 node·280 triangle·PID 1–7, CAD 연결 성분 2 |

판 NAS: `outputs/run_0932469103774fdeb5db689b3e2c9f9d/mesh.nas`, SHA256 `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`. 1·2단계 판 예제와 byte 단위로 동일하다.

mixed BREP NAS: `outputs/run_6628a268b5474d6a8ef3310812d76ef8/mesh.nas`, SHA256 `799e166162650b2cd50a99b4dfcccce0afdff15c21118c8aaf21b6e914822e66`. 이 예제의 독립 curve/point는 CAD에 남고 표면 NAS에는 포함하지 않는다. 각 발행 폴더에는 `mesh.nas` 하나만 있다.

환경: Python 3.12.14, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1, pytest 8.4.2. Gmsh DLL SHA256은 `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`이다. 테스트·개발 fixture·smoke NAS는 새 로컬 프로젝트에만 생성했다. 보관본·원래 BRL 캐시·권한은 변경하지 않았다.

## 다음 단계와 한계

4단계는 특징별 크기장·폭/간극·유지 범위와 전이 거리·하한 충돌을 구현한다. 이후 편차 기반 곡률·자원 제한 및 단순/복잡 CAD 통합 검증을 진행한다. 직접 primitive 입력은 현재 plate이며 추가 형상은 해당 요구 검증과 함께 확장한다.

기존 node/edge 감사가 임의의 모든 face/face 교차를 증명하지 않는다. CAD 편차는 표본 지표이고 전체 곡면의 최대 편차 보증은 이후 단계의 요구다. 기하/품질/NAS 검증은 EM 관측량 수렴이나 정확도 보증이 아니다. 실제 작업 CAD·UI 시각 확인·대형 CAD 반응성과 자원 한도는 6단계 통합 검증에서 확인한다.

## 공식 근거

- [Gmsh 4.15.2 geometry options](https://gmsh.info/doc/texinfo/gmsh.html#Geometry-options): `OCCTargetUnit`·`OCCScaling`.
- [Gmsh OCC API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002focc): importShapes·highestDimOnly·명시적 format.
- [Gmsh ONELAB API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fonelab), [FLTK API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002ffltk): parameter·main-thread event loop.
- [Gmsh 4.15.2 OCC source](https://raw.githubusercontent.com/live-clones/gmsh/gmsh_4_15_2/src/geo/GModelIO_OCC.cpp): STEP/IGES target-unit 초기화 순서 및 import compound scaling 경로. source 읽기와 이 환경의 실제 새 프로세스 검증을 구분했다.
