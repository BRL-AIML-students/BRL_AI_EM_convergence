# 개발 및 협업

## 로컬 환경

Windows x64 저장소 루트에서 `setup.bat`을 실행합니다. 스크립트는 Python 3.12.14와 uv 0.12.20을 사용하고, 루트 `.venv`에 잠금 파일(`uv.lock`)의 의존성을 `uv sync --locked`로 설치합니다. 같은 버전의 64비트 Python을 찾지 못하면 uv가 저장소 `.tools` 아래에 설치합니다. uv 실행 파일은 버전과 SHA-256을 확인해 받으며, 런타임 파일과 다운로드 캐시는 `.tools`와 `.cache`에 보관합니다. 기존 Python 경로를 명시하려면 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonExecutable C:\Python312\python.exe`를 사용합니다. 초기 설정에는 인터넷 연결이 필요합니다. 이후 메시 UI와 뷰어의 정상 로컬 사용에는 인터넷 연결이 필요하지 않습니다.

잠금 파일 변경 후에는 setup을 다시 실행합니다. 개발 도구가 필요하면 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev`를 사용합니다. 저장소 경로를 옮기면 이전 `.venv`를 삭제하고 setup을 다시 실행합니다. 테스트는 저장소 루트에서 다음 명령으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

NAS 브라우저 뷰어의 JavaScript 파서 검사는 Node.js로 실행합니다. 명령은 `01_mesh_generator` 폴더에서 실행합니다.

```powershell
node .\tests\test_viewer_js.cjs
```

## 작업 공간과 파일

`BRL.code-workspace`를 VS Code에서 열어 작업합니다. `.venv`, 런타임 도구와 캐시, CAD 입력, 출력 및 테스트 산출물은 개인 작업용으로 저장소의 제외 규칙을 따릅니다. 추적 대상 코드는 설정된 재현 환경과 인터페이스를 기준으로 변경합니다.

## GitHub 협업

이 저장소의 기본 공개 저장소는 `HyunJoong-Kim-cnu/BRL_AI_EM_convergence`이며 기본 브랜치는 `main`입니다. 기능 작업은 브랜치에서 진행하고, 공유가 필요하면 변경 내용과 확인 방법을 담은 PR로 제안합니다. PR 설명에는 관련 CLI/UI 경로, NAS 또는 보고서 계약 변경, 수행한 검증을 기록합니다. 코드 리뷰와 병합은 GitHub PR에서 진행합니다.
