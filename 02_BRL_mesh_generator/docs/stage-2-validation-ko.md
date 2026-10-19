# 2단계: 품질 정책·필수 검사·개선과 rollback

작성일: 2026-10-19. 기준: 1단계 commit `9872d52` 이후 로컬 `codex/rebuild-core` 작업. GitHub 작업은 최종 단계로 보류한다.

## 완료한 범위

- 요소 품질 계산·판정, topology, CAD 법선, 기하 보존 값과 개선 제어를 별도 모듈로 분리했다. score/profile/report 구조는 없다.
- CLI의 단일 판 생성→현재 검사→필요한 개선→현재 재검사→독립 NAS 검증·발행에 연결했다.
- 일반화된 내부 검사 코어는 실제 OCC box·sphere 및 인위적으로 손상한 메쉬에서도 검증했다. STEP/IGES/BREP 파일 입력과 ONELAB은 아직 구현하지 않았다.

## 확정한 품질 정책과 계산 경로

개발용 비교 명령:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m tools.quality_policy_probe
```

기준 edge (0,0)→(1,0), 세 번째 점 (x,h)의 104개 1차 삼각형을 Gmsh 4.15.2에서 평가했다. 기존 AR ≤ 3·최소각 ≥ 20° 조건에 57개가 통과했다. 다음 두 사례가 단일 ICN 하한으로 기존 판정을 보존할 수 없음을 보여준다.

| (x,h) | AR | 최소각 | Plugin ICN | 기존 조건 |
|---|---:|---:|---:|---|
| (0.5, 0.2) | 2.9979388485 | 21.8014094864° | 0.4384938753 | 통과 |
| (0.5, 3.0) | 2.0728203787 | 18.9246444161° | 0.5329387100 | 차단 |

따라서 다음으로 확정했다.

- AR·최소각은 기존 발행 조건으로 유지한다. 별도 계산이 남는 이유는 ICN 단일 기준과 수용/거부 집합이 다르기 때문이다. 기존 임계값을 ICN으로 환산하지 않는다.
- `AnalyseMeshQuality`의 ICN만 활성화하고 유효한 element ID/유한 양의 결과를 확인한다. 이 유효성 확인은 CAD 바깥 방향 판정이 아니다. 별도의 경험적 ICN 발행 하한은 도입하지 않았다.
- 개선 후보의 최소 ICN 비악화와 상승 여부를 실제 수용 판단에 사용한다. 사용하지 않는 Jacobian·IGE measure는 0으로 명시한다.
- API `minSICN`과 Plugin ICN의 최대 차이는 이 104개 1차 삼각형에서 약 `3.23e-15`였다. 일반 요소·고차 요소·부호·sampling의 동등성으로 확대하지 않는다. 현재는 검증된 Plugin 경로를 선택했고 자동 fallback은 없다.
- 퇴화 사례는 품질 계산 전에 구조 검사에서 차단한다. 이 비교는 기하 정책의 선택 근거이며 EM 정확도 기준이나 MoM 행렬 조건수 검증이 아니다.

## 검사 책임

| 모듈 | 검사/소비 역할 |
|---|---|
| `model.py` | 유한 좌표·ID·중복/퇴화 요소·유효 연결, 현재 snapshot 일치, 불변 구조 비교 |
| `checks.py` | AR·최소각 원시 값과 판정; 별도로 단일 판의 평면·범위·면적 확인 |
| `quality.py` | Plugin ICN 재계산·element ID 대응·view 정리·표시 상태 보존. stale snapshot과 누락 결과 차단 |
| `topology.py` | edge 공유·연결 성분·예상 경계·winding·nonmanifold vertex fan·node/edge 공간 관계 |
| `normals.py` | CAD projection/normal, 실제 solid 양쪽 점 분류로 바깥 방향 확인; 열린 sheet는 명시한 CAD parameter normal의 ± 기준 사용 |
| `preservation.py` | CAD face별 면적 상대 오차와 solid별 체적 상대 오차. 열린 sheet의 체적은 적용 불가(None)로 구분 |
| `inspection.py` | 위 결과를 한 현재 상태에서 결합. blocked/incomplete 사유는 모두 발행 차단; 점수 없이 원시 값만 제공 |
| `improvement.py` | 개선 가능 여부·횟수 제한·후보 수용·정확한 rollback 및 복구 실패 차단 |

열린/닫힌 경계와 기대 연결 성분 수는 명시적 계약이다. CAD 경계 line 요소에서 기대 열린 edge를 구성하며, 관측된 삼각형의 구멍을 그대로 허용 경계로 채택하지 않는다. 의도한 분리 surface 쌍과 gap은 보존하고 좌표를 자동 병합하지 않는다.

공간 검사는 edge별 길이·좌표 정밀도에 따른 tolerance와 AABB 후보 검색을 사용한다. 정확한 내부 node-on-edge는 T-junction으로 차단한다. 확실하지 않은 근접, gap과 tolerance 충돌, 후보 검사 한도 초과는 incomplete다. 기본 상대 tolerance `1e-9`, 후보 검사 한도 `200000`은 구현상의 검사 조건이며 보편적인 정확도 기준이 아니다. AABB 후보에 들어왔다는 이유만으로 gap 충돌로 판정하지 않고 실제 거리를 확인한다.

CAD 방향을 정하지 못하거나 필요한 projection·면적/체적 계산·Plugin 계산이 실패하면 정상으로 처리하지 않는다. solid가 공유하는 내부 면은 임의로 한쪽의 바깥 방향을 선택하지 않고 incomplete로 차단한다.

## 개선·복구 동작

`improvement.enabled` 기본값 true, `max_passes` 기본값 3·허용 범위 0–10. 정상 형상에는 재배치를 수행하지 않고 불량 형상에만 `Relocate2D`·`Laplace2D`를 번갈아 적용한다. 비활성화 또는 0회 설정은 개선만 생략하며 검사와 발행 차단을 해제하지 않는다.

1. 현재 검사에서 topology·법선·기하/품질 계산에 차단 또는 미완료가 있으면 재배치를 시작하지 않는다.
2. 모든 node의 좌표·parametric coordinate·dim/entity 분류, surface mesh의 ID/connectivity/PID, Physical Group, CAD entity와 모든 차원의 mesh 연결을 메모리에 확보한다.
3. 후보에 대해 새 snapshot과 Plugin 재계산을 수행한다. 불량 요소 수가 줄거나 같은 개수에서 최소 ICN이 올라야 하며, AR·최소각·최소 ICN이 악화되지 않아야 한다.
4. 최대 edge/목표 길이 비율·인접 요소 크기비·CAD centroid/node 편차·면적/체적 상대 오차가 악화되면 거부한다. 기하 값 비교에는 길이 단위와 좌표 규모에 맞춘 부동소수점 잡음 허용만 적용한다. point/curve의 고정 node는 좌표와 parameter를 보존한다.
5. 같은 구조의 거부 후보는 좌표·parameter를 정확히 복구하고 재검사한다. 퇴화/비유한 후보도 구조가 같으면 복구할 수 있도록 내부 raw snapshot 경로를 구분했다. raw snapshot은 발행/정상 판정에 사용하지 않는다.
6. 연결·ID·PID·entity·CAD 경계 연결이 달라지면 좌표 복구만으로 원상태라 주장하지 않고 차단한다. 복구 실패도 차단한다. 실행 중 예외로 일부 좌표만 이동했으면 가능한 정확한 복구 후 오류를 반환한다.
7. 최종 NAS 직전에는 현재 model에서 다시 검사한다. 과거 검사나 숨겨진 요소의 표시 상태로 발행 대상을 바꾸지 않는다.

## 실행 증거와 검증

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage2-final
```

전체 92개 테스트 통과(1단계 회귀 포함). Gmsh DLL과 pytest의 Windows FD capture 충돌을 피하는 기존 `--capture=sys` 설정을 사용했다.

- 실제 왜곡 판: 형상 불량 요소 2개·최소 ICN 약 0.27502315에서 `Relocate2D` 한 번을 수용해 불량 0개·최소 ICN 약 0.80159197로 개선.
- 실제 `Laplace2D` 경로 및 closed box 개선의 수용, 면적·체적 보존 확인.
- 악화·퇴화·CAD 이탈·고정 node 이동 후보의 정확한 좌표/parameter/classification 복구.
- surface 연결·CAD 경계 연결·Physical Group/PID·entity 변경, optimizer 중단·복구 실패 시 차단.
- 좋은 형상인데 연결이 분리된 사례, T-junction, nonmanifold edge/vertex, 예상 경계/연결 성분 불일치, 불확실한 근접·검사 예산 소진 차단.
- 의도한 열린 경계·작은 분리 gap 보존. 열린 sheet 기준 미지정·반대 winding·solid 바깥 방향 불일치 차단.
- CAD parameter normal을 뒤집어 제공해도 solid 점 분류로 실제 바깥 방향 확인. projection 실패는 incomplete.
- Plugin 오류·결과 ID 누락·stale snapshot·재계산·view/표시 보존, 개선 한도·비활성화와 발행 차단 확인.
- 별도 CLI에서 개선을 끈 불량 판도 종료 코드 2·blocked 상태로 종료하고 NAS를 만들지 않음.
- 크기·gradation·centroid/node 편차·면적/체적 보존 값의 악화 증거가 있으면 형상이 좋아져도 거부.
- 기존 NAS 손상·독립 읽기 실패·기존 출력 보존 검증 유지.

현재 예제(100×60 mm, 목표 10 mm)는 91 node·148 triangle을 생성했다. `outputs/run_9ddb7be6840040bd84a8b8c461f0504d/mesh.nas`의 SHA256은 `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`로 1단계 예제와 byte 단위로 동일하다. 예제 실행 폴더에는 NAS 한 파일만 있다.

환경은 Python 3.12.14·Gmsh 4.15.2·NumPy 1.26.4·pyNastran 1.4.1·pytest 8.4.2다. Gmsh library `.venv/Lib/gmsh-4.15.dll`의 SHA256은 `6cac3eefb477265d9fa60bbd869dbbbf7c7ca4cb308c0f8f2b43e91d43de3c1c`이다. 이는 이 환경의 식별값이며 다른 build에서 같은 결과를 보장하지 않는다.

## 남은 범위

CLI는 여전히 단일 판만 입력한다. 내부 CAD primitive 검증을 STEP/IGES/BREP 입력·ONELAB 구현 완료로 해석하지 않는다. 3단계에서 이 코어에 입력·UI·단위/PID 계약을 연결한다.

node/edge topology 검사는 임의의 face/face 자기 교차 전부를 증명하지 않는다. CAD centroid 편차도 표본 기반 값이며 전체 곡면 최대 오차 보증이 아니다. 요소 품질·기하/NAS 통과는 EM 정확도 보증이 아니다. 해당 범위는 추후 기하 요구·관측량별 검증과 구분한다.

보관본·원래 BRL 캐시·권한은 이번 단계에서 변경하지 않았다. 로컬 commit을 보존하고 GitHub PR·merge·branch 삭제는 사용자 지침에 따라 최종 시점까지 진행하지 않는다.

## 공식 근거

- [Gmsh 4.15.2 AnalyseMeshQuality](https://gmsh.info/doc/texinfo/gmsh.html#Plugin_0028AnalyseMeshQuality_0029): measure·임시 model-based view·재계산·표시 숨김의 기능 범위.
- [Gmsh mesh API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002fmesh): optimize·현재 node/element·분류 정보 API.
- [Gmsh model API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel): CAD projection·normal·solid 점 분류 API. 수용 정책과 복구 절차는 BRL의 구현·검증 결정이다.
