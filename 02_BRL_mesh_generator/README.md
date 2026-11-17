# BRL CAD 표면 메쉬 생성기

STEP·IGES·BREP의 표면을 1차 삼각형으로 분할하고, 검증된 NAS와 대응하는 단일 HTML 품질 보고서를 생성합니다. Python 함수 또는 CLI를 통해 호출하며, 실제 삼각분할은 공통 Gmsh 엔진이 담당합니다.

## 문서

| 문서 | 확인할 내용 |
|---|---|
| [01 프로그램 구성과 사용 인터페이스](docs/01_프로그램구성과사용인터페이스.html) | 의존성, 모듈 책임, Python 함수·CLI 계약, 설정 병합, 반환값과 오류 처리 |
| [02 설정변수 빠른 참조](docs/02_설정변수빠른참조.html) | 변환기의 전체 변수, 자료형·기본값·단위·범위·활성 조건·관련 원리 |
| [03 메쉬 생성 원리와 품질 평가](docs/03_메쉬생성원리와품질평가.html) | 크기장 결합, 곡률과 CAD 편차, 생성 알고리즘, 품질·필수 검사, 개선·재생성, NAS 검증 |

HTML은 브라우저에서 직접 열어 읽습니다. 스타일·목차·검색 기능·MathML 수식·그림을 파일 안에 포함하며 외부 CDN을 사용하지 않습니다.

## 코드에서 사용하는 인터페이스

진입점은 `convert_cad_to_nastran_surface_mesh.py`입니다.

| 인터페이스 | 역할 |
|---|---|
| `convert_cad_to_nas` | CAD 한 개를 변환하고 `ConversionResult` 반환. 실패 시 `ConversionError.result` 제공 |
| `ConversionJob` / `convert_many` | 작업별 설정을 갖는 순차 변환과 결과 iterator |
| `jobs_from_directory` | 디렉터리에서 CAD 작업 목록 구성 |
| `load_mesh_options` | 옵션 JSON 읽기·기본값 병합·검증 |
| `main` / CLI | 다른 언어·환경에서 호출하고 작업별 JSON 및 종료 코드 수신 |

`options`와 이름별 keyword override로 변수를 설정합니다. 전체 변수와 개별 활성화 스위치는 [빠른 참조](docs/02_설정변수빠른참조.html#reading)에 있습니다. 호출 프로세스가 작업마다 새 worker를 실행하므로 호출자가 가진 Gmsh model과 실행 session을 분리합니다.

## 환경과 입력 계약

Python 3.12 계열을 지원하며 저장된 버전은 3.12.14입니다. 고정 의존성은 Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1입니다. [setup.ps1](setup.ps1)은 저장소 전용 실행 환경을 준비하고, 의존성은 `pyproject.toml`과 `uv.lock`에서 관리합니다. 별도 환경의 worker Python은 `python_executable`로 지정합니다.

Windows에서 개발 의존성까지 설치하고 테스트하려면 이 폴더에서 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest
```

전체 원본에는 Gmsh ONELAB 인터페이스도 포함되어 있으며 `run_gmsh_onelab_mesh_interface.bat`으로 실행할 수 있습니다. 최소 CAD 변환 배포에는 이 선택 기능이 포함되지 않습니다.

현재 Windows 설치 루트는 ASCII 경로를 사용해야 합니다. CAD 입력·NAS 출력의 한글 경로는 별도 지원합니다. 프로그램은 로컬 `.cache`에 작업 파일을 생성하므로 설치 루트와 출력 폴더에 쓰기 권한이 필요합니다.

BREP는 `length_unit`이 필수이고 STEP·IGES는 파일 단위를 읽습니다. 길이·박스 좌표·편차 설정과 NAS 좌표는 `output_unit` 기준입니다. `target_size` 또는 독립적인 `mesh_frequency_hz` 중 하나를 활성 값으로 지정합니다. 열린 sheet는 CAD parameter normal에 대한 기준 부호가 필요합니다.

## 출력과 품질 정책

NAS는 `GRID`, `CTRIA3`, `ENDDATA` 및 주석 메타데이터로 구성합니다. 검증 과정에서 pyNastran으로 독립 재읽기하여 좌표·ID·연결·PID를 현재 메쉬와 대조합니다. PID는 CAD surface 대응이며 물성·MoM 경계조건을 자동 정의하지 않습니다.

ICN·IGE·AR·최소각·Radius Ratio는 각각 활성화와 기준을 지정합니다. 활성 기준 미달은 경고와 품질 보고서에 기록하고 NAS를 생성합니다. 퇴화·연결·경계·법선·CAD 보존·활성 필수 측정·독립 NAS 검증 오류는 출력을 차단합니다. `status=ok`는 파일 생성 완료이며 모든 품질 기준 통과를 뜻하지 않습니다.

IGE는 기본적으로 비활성화되어 있고 기본 하한은 `0.0`입니다. 활성화하면 유한한 양수 측정값을 검증하며, ICN이나 Radius Ratio와는 별도의 지표로 취급합니다.

NAS와 대응 보고서 중 하나라도 존재하면 덮어쓰지 않습니다. 보고서는 최종 NAS 해시와 적용 설정, 지표별 통계·분포·위반 요소 ID를 포함합니다. 형상 품질·파장 분할 수는 전자기 관측량의 정확도나 수렴을 보증하지 않습니다.

## 공통 원본과 배포

`brl_mesh/`가 공통 구현이며 `ui/`, `builtin_geometry/`, `development/`는 선택 기능입니다. `tools/package_cad_to_nastran_mesh_converter.py`는 공통 원본에서 최소 CAD 변환 배포를 구성합니다. 세 문서를 함께 포함하고 UI·기본 형상 구현·개발 계측·테스트·BAT·환경·캐시는 포함하지 않습니다. 배포본의 `ORIGIN.json`은 원본 커밋·작업 상태와 배포 파일 해시를 기록합니다. 배포본을 별도 원본으로 수정하지 않고 공통 원본을 갱신한 뒤 재생성합니다.
