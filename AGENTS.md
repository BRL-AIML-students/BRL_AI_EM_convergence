# BRL 작업 지침

- commit 메시지와 PR 제목·본문, 검증 설명은 한글로 작성한다. 주요 기술 용어, API 이름 및 파라미터는 영문을 유지한다.
- 독립 기능은 별도 branch·PR로 순차 진행하고, 의미 있는 commit을 보존하는 merge commit으로 병합한다.
- 기능의 코드, UI·CLI 연결 및 필요한 검증을 함께 관리한다. 사용자의 기존 변경과 무관한 파일은 commit에 포함하지 않는다.

## 현재 mesh generator와 GitHub 작업

- 사용자 지정 저장소는 `https://github.com/BRL-AIML-students/BRL_AI_EM_convergence.git`이다. 앞으로 수정·PR·merge는 이 저장소에서 진행한다.
- 현 구현은 `02_BRL_mesh_generator/`이다. 기존 `01_mesh_generator/` 전체와 전용 web UI·viewer·보고서 경로는 사용자 지시에 따라 제거했다. 이전 코드/입력 형식의 호환 계층을 다시 만들지 않는다.
- 모듈 내부 `AGENTS.md`와 검증 기록을 따른다. 환경·캐시는 모듈 내부에 구성하고 로컬 보관 archive는 수정하지 않는다.
- PR 작성과 merge를 구분한다. Merge는 명시적 사용자 지시가 있을 때 merge commit으로 수행하고, 성공·사용자 변경·미병합 commit·worktree를 확인한 후 해당 작업 branch만 로컬·원격에서 삭제한다.
