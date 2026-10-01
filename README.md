# BRL 전자기 메시 도구

CAD 형상에서 1차 삼각형 표면 메시를 만들고 NAS 파일과 품질 보고서를 생성하는 도구입니다. 브라우저 UI에서 형상을 설정하고 결과를 확인할 수 있습니다.

## 빠른 시작 (Windows)

Windows x64에서 처음 한 번은 인터넷 연결이 필요합니다. 저장소 루트에서 `setup.bat`을 실행하면 Python 3.12.14와 고정 버전 uv 0.12.20을 준비하고, `uv.lock` 기준으로 의존성을 설치합니다. uv는 같은 버전의 64비트 Python이 있으면 사용하고, 없으면 저장소 내부 `.tools`에 설치합니다. uv 실행 파일과 다운로드 캐시는 저장소의 `.tools`와 `.cache` 아래에 둡니다. 기존 Python 실행 파일을 지정할 경우 PowerShell에서 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonExecutable 'C:\경로\python.exe'`를 실행합니다. 이 `.venv`는 BRL 전용이며 동료 프로젝트 환경에는 영향을 주지 않습니다.

설치가 끝나면 `01_mesh_generator\run_ui.bat`을 실행하세요. 로컬 브라우저가 열리고, 기본 브라우저에서 형상 입력과 메시 생성 및 결과 확인을 할 수 있습니다. 서버를 끝낼 때는 UI의 종료 버튼을 사용하거나 실행 콘솔에서 Ctrl+C를 누릅니다. 메시 생성 결과와 CAD 입력 파일은 저장소의 Git 제외 경로에 보관됩니다.

의존성 잠금 파일을 갱신한 뒤에는 루트의 `setup.bat`을 다시 실행합니다. 개발 의존성(테스트 도구)까지 설치하려면 PowerShell에서 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev`를 실행합니다. 저장소 폴더를 이동한 뒤에는 이전 `.venv`를 삭제하고 setup을 다시 실행해야 합니다.

## VS Code

`BRL.code-workspace`를 열면 저장소 작업 공간을 사용할 수 있습니다. 프로젝트 가상환경은 저장소 루트의 `.venv`에 생성됩니다. 이 환경은 이 저장소에서만 사용되며, 동료 프로젝트의 Python이나 패키지 설정에 영향을 주지 않습니다.

## CLI

`01_mesh_generator` 폴더에서 JSON 설정 파일을 실행합니다.

```powershell
..\.venv\Scripts\python.exe -m geometry_mesh.cli examples\plate_wave_local.json
```

CLI는 결과 위치와 상태를 JSON으로 출력합니다. 프로필 및 NAS 형식은 [메시 인터페이스](docs/mesh-interface.md)를 참고하세요. 생성 기준·종횡비·연결 검사와 참고문헌은 [메시 생성 기준](docs/mesh-generation-guide.md)에 정리되어 있습니다.

## 개발과 협업

기본 테스트와 PR 협업 절차는 [개발 안내](docs/DEVELOPMENT.md)에 있습니다. 공개 대상은 이 저장소에서 제공하는 메시 생성기와 NAS 뷰어입니다.
