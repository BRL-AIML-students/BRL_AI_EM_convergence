# BRL 표면 메시 생성기 — CAD에서 NAS까지

**CAD 파일의 표면을 삼각형으로 나누고, MoM 코드에서 읽을 수 있는 `.nas` 파일로 저장합니다.**
CAD 하나를 변환하거나 여러 CAD를 순서대로 처리할 수 있습니다. 변환 중 UI를 열 필요는 없습니다.

```text
STEP / IGES / BREP + 설정
          ↓
CAD 읽기 → 형상에 맞는 옵션 선택 → 삼각형 메시 생성 → 검사·개선
          ↓
검증된 .nas 파일 → 사용자의 MoM reader → 전자기 해석
```

생성기는 표면 메시를 준비합니다. MoM 계산은 상대방의 기존 코드가 담당하며,
그 코드를 이 프로젝트에 제공할 필요는 없습니다. 아래 순서대로 진행하세요.

메쉬 옵션은 [편집용 JSON](examples/cad_to_nastran_mesh_options.json)에서 켜고 끄고 값을 바꿉니다.
ICN·AR·최소각·radius ratio는 `quality`에서 각각 설정하며, 메쉬용 주파수는 MoM 변수와 독립인
`mesh_frequency_hz`입니다. [전체 옵션 설명서](docs/01_사용방법과설정.html)에 단위·범위·
설정 우선순위와 MoM 연결 예제가 있습니다. 평가만 별도로 편집할 때는
[평가 설정 JSON](examples/mesh_quality_options.json)을 `--quality`로 지정하세요.

2026-11-16에 내부 Python 모듈까지 역할 중심 이름으로 변경했습니다.
기존 import·실행 파일명은 [파일명 대응표](docs/02_구조와코드해설.html#file-migration)를 따라 갱신하세요.
내부 주파수 키도 `mesh.wave.mesh_frequency_hz`이며 이전 `frequency_hz`는 지원하지 않습니다.

## 1. 준비할 것

| 준비물 | 설명 |
|---|---|
| Windows x64 컴퓨터 | 최초 설치에는 인터넷 연결이 필요합니다. |
| 생성기 폴더 전체 | ZIP을 풀고 `setup.ps1`이 있는 폴더를 찾으세요. `convert_cad_to_nastran_surface_mesh.py`만 복사하면 실행할 수 없습니다. |
| 입력 CAD | `.step`, `.stp`, `.iges`, `.igs`, `.brep`를 지원합니다. STL은 지원하지 않습니다. |
| 입력 단위와 원하는 목표 길이 | BREP 좌표 단위를 확인하세요. 출력 좌표 단위와 메시 목표 길이를 지정합니다. |

다른 PC에는 ZIP을 **영문 로컬 경로**에 풀어 사용하세요. 예: `C:\BRL\CAD_to_NAS`.
공백과 CAD 입력·NAS 출력 경로의 한글은 지원하지만, 현재 Windows Gmsh의 내부 파일 저장 때문에
**생성기 설치 경로에는 한글 등 비 ASCII 문자를 사용할 수 없습니다.**
설치·캐시·중간 작업은 로컬에서 수행하고, 필요한 최종 NAS만 공유/동기화 폴더에 저장하세요.

## 2. 최초 한 번 설치하기

PowerShell을 열고 **`setup.ps1`이 있는 폴더**로 이동합니다. 아래 경로는 실제 설치 위치로 바꾸세요.
현재 저장소를 사용한다면 `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`입니다.

```powershell
Set-Location "C:\BRL\CAD_to_NAS"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

설치 스크립트는 이 폴더에 전용 Python과 필요한 라이브러리를 준비합니다.
Python 3.12.14, Gmsh 4.15.2, NumPy 1.26.4, pyNastran 1.4.1을 고정된 의존성 정보로 설치합니다.
MoM용 Python 환경을 바꿀 필요는 없습니다. 다른 PC의 `.venv`를 복사하지 말고 해당 PC에서 설치하세요.

## 3. 포함된 CAD 하나로 먼저 확인하기

자신의 CAD를 사용하기 전에 포함된 원통 예제를 실행하세요.

```powershell
.\run_cad_to_nastran_surface_mesh.bat --jobs .\examples\cad_to_nastran_conversion_jobs.json
```

성공하면 화면에 JSON 응답이 나오고, 생성기 폴더 아래 다음 파일이 생깁니다.

```text
outputs/cad-to-nas/cylinder.nas
```

응답의 `"status": "ok"`가 성공을 뜻합니다. `nas_path`는 완성된 파일의 경로,
`node_count`와 `triangle_count`는 노드와 삼각형 수입니다.

**이미 같은 NAS가 있으면 덮어쓰지 않습니다.** 예제를 다시 실행하려면
`examples/cad_to_nastran_conversion_jobs.json`의 `nas_path`를 `../outputs/cad-to-nas/cylinder_02.nas`처럼 바꾸세요.

## 4. 자신의 CAD로 바꾸기

입력 경로와 출력 경로, 목표 길이를 지정합니다. 아래 예시는 출력 좌표 단위가 기본값인 m이고,
목표 길이 `0.005`는 **5 mm**입니다. 처음에는 닫힌 solid CAD로 확인하면 방향 설정이 간단합니다.

```powershell
.\run_cad_to_nastran_surface_mesh.bat --cad "C:\CAD\model.step" --nas "C:\NAS\model.nas" --target-size 0.005
```

BREP는 파일의 좌표 단위를 명시합니다. 다음은 입력 좌표가 mm인 경우입니다.

```powershell
.\run_cad_to_nastran_surface_mesh.bat --cad "C:\CAD\model.brep" --nas "C:\NAS\model.nas" --length-unit mm --target-size 0.005
```

STEP/IGES는 파일에 저장된 단위를 읽습니다. `length_unit`으로 그 단위를 덮어쓰지 않습니다.

### 열린 판(sheet)을 입력한다면

두께 없는 판처럼 solid에 속하지 않는 표면은 기준 법선 방향을 지정해야 합니다.
다음은 CAD parameter normal의 **+방향을 의도적으로 선택한 예시**입니다.

```powershell
.\run_cad_to_nastran_surface_mesh.bat --cad "C:\CAD\sheet.step" --nas "C:\NAS\sheet.nas" --target-size 0.005 --sheet-normal 1
```

`1`이 항상 원하는 물리적 방향을 뜻하지는 않습니다. 반대 방향은 `-1`이며,
면마다 방향이 다르면 `sheet_normals`로 지정합니다. 방향을 지정하지 않으면 필요한 surface tag를 오류로 알려줍니다.

## 5. 옵션을 설정하기

생성기 폴더에 `settings.json`을 만들고 다음을 저장하세요. JSON에는 주석을 넣지 않습니다.

```json
{
  "length_unit": "mm",
  "output_unit": "m",
  "target_size": 0.005,
  "curvature": "auto",
  "curvature_tolerance_ratio": 0.02,
  "short_edges": "auto",
  "widths": "auto",
  "gaps": false,
  "improvement": true
}
```

```powershell
.\run_cad_to_nastran_surface_mesh.bat --cad "C:\CAD\model.step" --nas "C:\NAS\model.nas" --options .\settings.json
```

| 바꿀 값 | 하는 일 | 위 예시의 의미 |
|---|---|---|
| `output_unit` | NAS 좌표와 길이 설정에 사용할 단위 | `m`: 미터 |
| `target_size` | 기본 메시 목표 길이 | `0.005`: 5 mm. 실제 최대 edge 길이의 보증값은 아닙니다. |
| `curvature` | 곡면과 곡선 경계의 표현을 제어 | `auto`: 곡면 또는 곡선 경계가 있으면 사용 |
| `curvature_tolerance_ratio` | 곡률 허용편차를 기본 목표 길이의 비율로 설정 | `0.02`: 5 mm × 2% = 0.1 mm |
| `short_edges` | 짧은 CAD edge 주변을 세분화 | `auto`: 적용할 edge를 자동 선택 |
| `widths` | 좁은 폭을 가진 지원 대상 면을 세분화 | `auto`: 직선 경계의 볼록 평면만 선택 |
| `gaps` | 독립된 면 사이 간격을 기준으로 세분화 | `false`: 사용하지 않음 |
| `improvement` | 기존 품질 개선 절차를 실행 | `true`: 사용 |

`curvature`, `short_edges`, `widths`, `gaps`는 JSON에서 `true` / `false` / `"auto"`를 받습니다.
Python에서는 `True` / `False` / `"auto"`, 명령행에서는 `on` / `off` / `auto`로 씁니다.
`improvement`는 켜기/끄기만 지원합니다.

곡률 허용편차를 직접 정하려면 `"curvature_absolute_tolerance": 0.0001`을 추가하세요.
출력 단위가 m이면 0.1 mm이며, 직접 지정한 허용편차가 비율 계산보다 우선합니다.
같은 목표 길이라도 곡률 제어를 켜면 필요한 영역에서 요소 수가 늘어날 수 있습니다.
2%는 조절 가능한 초기값이며 MoM 정확도를 보증하는 기준은 아닙니다.

기본 목표 길이 대신 `mesh_frequency_hz`와 `elements_per_wavelength`를 지정할 수도 있습니다.
세부 옵션·단위·적용 우선순위는 [상세 사용 설명서](docs/01_사용방법과설정.html#settings)에 있습니다.

## 6. 여러 CAD를 한 번에 변환하기

같은 옵션을 쓸 때는 입력 폴더를 지정하는 것이 가장 간단합니다.

```powershell
.\run_cad_to_nastran_surface_mesh.bat --input-dir "C:\CAD" --output-dir "C:\NAS\run_01" --recursive --options .\settings.json
```

```text
입력                           출력
C:\CAD\antenna.step            C:\NAS\run_01\antenna.step.nas
C:\CAD\plate.iges              C:\NAS\run_01\plate.iges.nas
C:\CAD\sub\part.brep           C:\NAS\run_01\sub\part.brep.nas
```

`--recursive`는 하위 폴더도 읽습니다. 없으면 지정한 폴더 바로 아래의 CAD만 처리합니다.
각 CAD는 별도 프로세스에서 **순차 처리**하며, 하나가 실패해도 다음 CAD로 넘어갑니다.
첫 실패에서 멈추려면 `--stop-on-error`를 추가하세요. 재실행할 때는 `run_02`처럼 새 출력 폴더를 쓰세요.

### CAD마다 옵션이 다를 때

다음 구조의 `jobs.json`을 만들고 `--jobs`로 실행합니다. 경로와 형상 이름은 자신의 파일에 맞게 바꾸세요.

```json
{
  "default_options": {
    "output_unit": "m",
    "target_size": 0.005,
    "curvature": "auto"
  },
  "jobs": [
    {
      "cad_path": "C:/CAD/sphere.step",
      "nas_path": "C:/NAS/run_02/sphere.nas",
      "options": {"curvature_absolute_tolerance": 0.00005}
    },
    {
      "cad_path": "C:/CAD/plate.step",
      "nas_path": "C:/NAS/run_02/plate.nas",
      "options": {"curvature": false, "sheet_normal": 1}
    }
  ]
}
```

```powershell
.\run_cad_to_nastran_surface_mesh.bat --jobs .\jobs.json
```

`default_options`는 공통값이고 각 job의 `options`가 우선합니다.
jobs JSON 안의 상대 경로는 **그 JSON이 있는 폴더 기준**입니다.
일반 `--cad`, `--nas`, `--input-dir`의 상대 경로는 **명령을 실행한 폴더 기준**입니다.

## 7. Python 함수로 호출하고 MoM에 연결하기

아래 코드를 `convert_cad_to_nastran_surface_mesh.py`와 같은 폴더에 `example_batch.py`로 저장하세요.
`C:\CAD`에 입력 CAD를 준비하고, `options`에서 단위와 목표 길이를 맞춥니다.

```python
from datetime import datetime
from pathlib import Path
from convert_cad_to_nastran_surface_mesh import convert_many, jobs_from_directory

base = Path(__file__).resolve().parent
output_dir = Path(r"C:\NAS") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
jobs = jobs_from_directory(r"C:\CAD", output_dir, recursive=True)

options = {
    "length_unit": "mm",  # BREP 입력 단위
    "output_unit": "m",   # 출력 단위
    "target_size": 0.005, # 5 mm
    "curvature": "auto",
    "curvature_tolerance_ratio": 0.02,
    "short_edges": "auto",
    "widths": "auto",
    "gaps": False,
    "improvement": True,
}

if not jobs:
    raise SystemExit("입력 폴더에 지원하는 CAD가 없습니다.")

for result in convert_many(
    jobs,
    default_options=options,
    continue_on_error=True,
    python_executable=base / ".venv" / "Scripts" / "python.exe",
):
    if result.status != "ok":
        print(f"실패: {result.cad_path.name} / {result.reason}")
        continue

    print(f"완료: {result.nas_path}")
    print(f"노드 {result.node_count}, 삼각형 {result.triangle_count}")

    # 상대방이 자신의 MoM 함수 호출을 여기에 넣습니다.
    # 예: run_mom(str(result.nas_path))
```

```powershell
.\.venv\Scripts\python.exe -B .\example_batch.py
```

이 반복문에 MoM 계산을 연결하면 `CAD 1 변환 → MoM 계산 → CAD 2 변환 → MoM 계산` 순서가 됩니다.
열린 sheet는 공통 또는 CAD별 옵션으로 설계 의도에 맞는 기준 방향을 추가해야 합니다.
한 CAD만 변환할 때는 `convert_cad_to_nas(cad_path, nas_path, options=options)`를 사용합니다.
이는 실패 시 `ConversionError`를 발생시키며, 여러 CAD용 `convert_many`는 기본적으로 실패도 결과로 반환합니다.

**MoM이 Python으로 작성되지 않았거나 다른 Python 환경을 써도 연결할 수 있습니다.**
상대방 언어의 외부 프로세스 실행 기능으로 `run_cad_to_nastran_surface_mesh.bat`를 호출하고,
종료를 기다린 뒤 각 JSON의 `status`가 `ok`인 `nas_path`만 읽으면 됩니다.

| 확인 항목 | 계약 |
|---|---|
| 출력 내용 | `GRID` 좌표, `CTRIA3` 삼각형 연결, `ENDDATA`, 단위·설정 주석 |
| 좌표 단위 | `output_unit`으로 지정한 단위. MoM에서 같은 단위로 해석해야 합니다. |
| PID | 현재 엔진의 CAD surface tag. MoM의 재료번호로 자동 변환하지 않습니다. |
| 성공 판단 | 파일 존재 대신 `status="ok"` 응답을 확인합니다. |
| 종료 코드 | 전체 성공 `0`, 입력·실행·전송 오류 포함 `1`, 메시 검사 차단만 포함 `2` |

MoM reader의 주석 처리, ID 처리, 열린 표면·법선·연결 조건은 상대방이 예제 NAS로 확인해야 합니다.
생성기는 MoM 해석이나 전자기적 수렴 검증을 실행하지 않습니다.

## 8. 실행이 안 될 때

| 상황 | 확인할 것 |
|---|---|
| `Run setup.ps1 first` | 설치 폴더에서 최초 설치를 완료했는지 확인합니다. |
| 설치 경로 오류 | 생성기를 영문 로컬 경로에 풀고 그 위치에서 설치합니다. |
| 기존 출력 덮어쓰기 오류 | 새 NAS 이름 또는 새 출력 폴더를 지정합니다. |
| `BREP에는 length_unit` | CAD 좌표에 맞는 `mm`, `m` 등의 입력 단위를 지정합니다. |
| 열린 sheet 기준 방향 오류 | `sheet_normal` 또는 surface별 `sheet_normals`를 지정합니다. |
| `width_unsupported` | `widths=true`로 지정한 면이 지원 대상인지 확인합니다. 지원 면만 자동 선택하려면 `auto`를 사용합니다. |
| 곡률·최소 크기·반복 한도 충돌 | 허용편차, 목표 길이, minimum_size, 반복 설정과 실제 CAD를 함께 확인합니다. 오류를 숨기려고 검사를 해제하지 않습니다. |

`warnings`가 있어도 status가 `ok`이면 성공입니다. 예를 들어 widths auto가 지원하지 않는 면을
제외했다는 안내일 수 있습니다. `blocked`는 메시가 필수 검사를 통과하지 못했다는 뜻입니다.
구조·법선·품질·독립 NAS 읽기 검사는 옵션 OFF로 해제되지 않습니다.

목표 길이와 실제 edge 길이는 다를 수 있고, 곡률 검사는 유한 표본의 CAD 편차 검사입니다.
메시 검사 통과만으로 MoM 해석의 정확도를 보장하지는 않습니다.

## 9. 기존 UI와 개발 자료

전체 저장소에는 기존 ONELAB UI도 있습니다. CAD→NAS 전용 ZIP에는 UI 실행 파일과 전체 예제가
들어 있지 않으므로, UI가 필요하면 전체 저장소를 사용하세요.

```powershell
# 전체 저장소에서 실행
.\run_gmsh_onelab_mesh_interface.bat examples\plate.json
# 기존 JSON 기반 CLI
.\run_mesh_generator_command_line.bat examples\ogive.json
```

UI의 `BRL/00 Action`에서 `Generate + publish NAS`를 선택하고 `BRL/02 NAS path`를 확인합니다.
일반 Gmsh File/Export는 BRL 발행 검사를 실행하지 않습니다.
기존 UI/CLI는 `outputs/run_<형상>_<치수>_<id>/mesh.nas`로 출력하며,
이 README의 CAD→NAS 진입점은 사용자가 지정한 `nas_path`로 출력합니다.

- [CAD→NAS 상세 사용 설명서](docs/01_사용방법과설정.html): 전체 함수·옵션·자동 선택·검사·파일 보호 규칙
- 전체 저장소의 `docs/02_구조와코드해설.html`: UI·native 형상·설정 그림. 로컬 브라우저로 열기
- 전체 저장소의 `docs/03_개발검증과변경이력.html`: 개발 검증·성능 측정·GitHub 기록

개발자는 `setup.ps1 -Dev`로 테스트 의존성을 설치하고 로컬 `.cache/tests`에서 검증합니다.
의존성은 `uv.lock`으로 고정합니다. 환경·Git 이력·캐시 전체를 임의로 이동하거나 삭제하지 않습니다.
