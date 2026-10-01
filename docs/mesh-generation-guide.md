# BRL 메시 생성 안내 문서

기준 문서는 [Gmsh 기반 meshgenerator: 작업 흐름·생성 원리·사용법](mesh-generation-guide.html)으로 전환했습니다.

HTML 파일을 내려받아 브라우저에서 열면 목차, MathML 수식, 실행 예제, 코드 위치와 전체 함수 발췌를 함께 읽을 수 있습니다. 본문에 필요한 CSS·JavaScript·예제·코드는 파일 안에 포함되어 있습니다. 외부 참고문헌과 GitHub 원문 링크는 인터넷 연결이 필요합니다.

설명 대상: 코드 커밋 `a20a40855ccc2fc4246b88eb11dc7028787a2979`, Gmsh 4.15.2. 본문의 코드 위치와 발췌는 이 고정 커밋을 기준으로 하며 이후 main 변경을 자동 반영하지 않습니다.

기존 생성·검사 기준, 참고문헌, PR 링크와 이전 문서 기록은 HTML 안에 보존했습니다. 다음 기능 추가·수정부터 PR 및 변경 이력을 누적합니다.

실행·파일 계약은 [mesh-interface.md](mesh-interface.md), 기존 검증 기록은 [VALIDATION.md](VALIDATION.md)에서도 확인할 수 있습니다.
