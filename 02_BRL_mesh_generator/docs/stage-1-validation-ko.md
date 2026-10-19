# 1단계: 단일 판 최소 코어 구현·검증

날짜: 2026-10-19. 작업 branch: `codex/rebuild-core`. 로컬 검증만 수행했고 원격 연결·push·PR·merge·branch 삭제는 하지 않았다.

## 구현 범위

| 영역 | 구현·검증 내용 |
|---|---|
| 독립 환경 | Python 3.12.14, uv 0.12.20, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1, pytest 8.4.2. Python base prefix·가상환경·Gmsh module 경로가 모두 새 프로젝트 안에 있음 |
| 입력 | schema_version=1, 알 수 없는 키·중복 JSON 키·비유한/음수 길이·미지원 형상·과거 controlled/compare 키 거부 |
| 단위·경로 | 입력 형상은 length_unit, 목표 길이는 output_unit, 상대 output_dir는 설정 파일 기준. mm→m 기하 변환 검증 |
| 생성 | XY 평면 단일 직사각형 판, +Z 기준 방향, 1차 삼각형, Algorithm 6, thread=1, seed=1 |
| 출력 검사 | 유한 좌표·양의 유일 ID·유효 연결·중복/퇴화 삼각형·기존 AR/최소각·판 범위/면적·기대 경계·연결성·winding·PID/surface 분류 |
| ICN adapter | AnalyseMeshQuality, DimensionOfElements=2, ICN만 활성화, Recompute=1, 임시 model-based ElementData를 element ID별로 읽고 정리 |
| 발행 | 임시 NAS 작성→strict parse→독립 pyNastran 읽기→좌표/ID/connectivity/PID 대조→고유 실행 폴더로 rename. 기존 결과 덮어쓰기 금지 |
| CLI | `python -m brl_mesh <config.json>`, run_cli.bat, 최소 상태 JSON, 정상 0·입력/실행 오류 1·검사 차단 2 |

판의 열린 경계는 기대한 경계로 허용한다. 일반 CAD의 gap·outward normal·T-junction·nonmanifold 검사가 모두 완료됐다는 의미가 아니다.

## 품질 정책의 현재 적용

ICN 중심 기준을 사례 검증으로 확정하기 전이므로 기존 운영 조건 AR ≤ 3·최소각 ≥ 20°만 출력 차단에 보존했다. AR 정의는 `Lmax * perimeter / (4 sqrt(3) area)`이다. 이 별도 계산이 남는 이유는 검증 없이 기존 필수 조건을 제거하지 않기 위해서이며, scoring profile·점수 wrapper는 사용하지 않는다.

ICN adapter는 개발 검증에 사용하고 출력 경로에 ICN 임계값을 중복 추가하지 않았다. IGE·Jacobian Plugin 경로 및 API와의 동등성 검증은 이 단계에서 구현하지 않았다. 2단계에서 정책과 자동화 경로를 확정한다. ICN 또는 형상 검사 통과는 EM 행렬 조건수·해석 정확도 보증이 아니다.

## 테스트 결과

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage1-final
```

전체 38개 테스트 통과. 다음의 성공·실패 경로를 포함한다.

- 정상 생성·같은 조건의 두 번 생성에서 NAS bytes 일치. 이 확인은 해당 단일 판·고정 환경에 한정하며 일반 재현성 보증이 아니다.
- 형상 품질은 정상이어도 공유 경계에서 node ID가 분리된 사례의 차단.
- 반대 winding·가느다란 요소·중복/누락 ID·중복/퇴화 삼각형·비유한 좌표 차단.
- sparse element ID 100·200의 Plugin 결과 대응, 기존 사용자 view 보존, 숨겨진 요소의 표시 상태 복구.
- node 이동 후 ICN 재계산으로 값 변경 확인. 결과 ID 누락 시 차단하고 임시 view 정리.
- NAS 좌표·연결·PID 변조, 중복 GRID, ENDDATA 누락/중복 거부.
- 독립 읽기 실패 시 정상 NAS 미발행·임시 파일 정리·기존 결과 보존.
- 실제 별도 프로세스 CLI 정상/잘못된 입력 종료 및 최소 JSON 상태 확인.

최초 실행에서는 pytest의 기본 FD capture가 Windows Gmsh DLL에서 `0xc0000008` 오류를 일으켰다. 직접 CLI는 정상 동작했고, 실패한 6개 테스트를 `--capture=sys`로 실행했을 때 모두 통과했다. 프로젝트 pytest 설정에 이 옵션을 포함한 후 전체 테스트가 통과했다. Gmsh 호출을 건너뛰거나 실패 검사를 약화하지 않았다.

## 실제 CLI 예제

`examples/plate.json`: 100 × 60 mm, origin=(0,0,0), target_size=10 mm.

- node 91개, triangle 148개, PID=1.
- 독립 reader에서 bbox min=(0,0,0), max=(100,60,0) mm 확인.
- 파일: `outputs/run_6a56431b9a0746c18c40df44d8c06ca5/mesh.nas`.
- SHA256: `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`.
- 해당 실행 폴더에는 NAS 한 파일만 있음. 개발 환경·캐시·outputs는 Git에서 제외한다.

## 이후 단계

2단계는 품질 기준/경로 확정, 일반화된 필수 topology·법선 검사와 개선 수용·정확한 rollback을 담당한다. ONELAB·STEP/IGES/BREP·특징별 크기장·곡률 편차·자원 제한 및 복잡 CAD 검증은 3–6단계다. 이번 단순 판 구현을 전체 생성기의 완료 또는 일반 CAD의 정상 출력 보증으로 표현하지 않는다.

각 단계는 로컬 작성·검증·commit으로 진행한다. GitHub PR은 전체 구현과 통합 검증 후 모아서 준비하고, 사용자의 명시적 merge 지시 후 병합 성공을 확인한 다음 작업 branch를 정리한다.
