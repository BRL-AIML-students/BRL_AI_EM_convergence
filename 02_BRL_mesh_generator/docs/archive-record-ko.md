# 기존 BRL 보관 기록

- 날짜: 2026-10-19 (Asia/Seoul)
- 이전 경로: `C:\Users\user1\Documents\Codex\BRL`
- 보관 경로: `C:\Users\user1\Documents\Codex\99_archive\BRL_2026-10-19`
- 새 작업 루트: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`
- 보관한 Git HEAD: `3eb636c1be9c2c59103d8f67267686f80ed01659`
- 이전 branch: `main`
- 이전 remote: `https://github.com/BRL-AIML-students/BRL_AI_EM_convergence.git` (보관 기록이며 새 프로젝트에 연결하지 않음)

## 보존 확인

기존 `.git`·소스·문서·입력 예제·outputs·도구·가상환경을 보관 폴더로 이동했다. Git HEAD와 `git status --short`가 이동 전후 동일한지 확인했다. 미추적 문서 두 파일의 SHA256도 이동 전후 일치한다.

| 미추적 문서 | SHA256 |
|---|---|
| `docs/mesh-generator-refactor-plan-ko.md` | `32D218B24302A4EA64D9DFD910E22A4F32F7031DD72AF9A690A8D7796DC2C4EA` |
| `docs/mesh-size-field-guide-ko.html` | `BA907CEDD591B1D6A3F0046E6CBCF4B9FD5C5DD60EC1536B8ACE663697460C9A` |

Git commit·push·원격 archive 설정 변경·기존 산출물 삭제는 수행하지 않았다. 폴더 보관은 로컬 작업이다. 이동 후 가상환경 실행을 검증하지 않았으며 새 프로젝트는 이를 사용하지 않는다.

## 원래 경로에 남은 항목

현재 프로세스가 원래 작업 폴더를 사용 중이어서 폴더 자체를 옮기지 못했다. 내용물을 이동했으며 접근이 거부된 `.pytest_cache`는 원래 위치에 보존했다. 기존 `BRL` 경로에는 이 캐시와 archive 안내만 남긴다. 캐시는 소스·Git 이력·사용자 문서에 포함되지 않으며 강제 삭제하지 않았다.

향후 정리할 경우 사용하는 프로세스를 종료하고 남은 경로·권한·내용을 재확인한다. 이 기록만으로 삭제를 자동 실행하지 않는다.

## 2026-10-19 원래 경로 삭제 재시도

사용자가 보관본 확인 후 원래 BRL 폴더의 삭제를 요청했다. 보관 Git HEAD·tracked diff·미추적 문서 두 파일의 SHA256을 재확인했고 이상이 없었다. 원래 경로에는 `.pytest_cache`와 안내 파일 두 개만 남아 있어 소스 보존 관점에서는 삭제 가능한 상태다.

Windows가 `.pytest_cache`에 대한 재귀 삭제·ACL 조회·현재 사용자 권한 부여를 모두 거부했다. 원래 BRL 디렉터리의 삭제는 미완료이며, 남아 있는 캐시와 안내 파일은 삭제하지 않았다. 보관본과 새 프로젝트에는 영향이 없다. 현재 프로세스 권한으로 더 진행하지 않고 추후 운영체제 권한 문제를 해결한 뒤 정리할 대상으로 남긴다.
