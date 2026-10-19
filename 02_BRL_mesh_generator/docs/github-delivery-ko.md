# 최종 GitHub 전달 준비

로컬 source: `C:\Users\user1\Documents\Codex\02_BRL_mesh_generator`, branch `codex/rebuild-core`.

2026-10-20 사용자 지정: 앞으로 수정·PR·merge 대상은 [BRL_AI_EM_convergence](https://github.com/BRL-AIML-students/BRL_AI_EM_convergence)이다. 기존 `01_mesh_generator/`를 전부 삭제하고 새 `02_BRL_mesh_generator/`로 대체한다. 구 구현용 루트 설정·실행 안내도 교체한다. Git 이력과 로컬 archive는 보존한다. 전달 checkout은 `.cache/github-delivery`이며 대상 main 위에 로컬 source 이력을 squash 없이 subtree로 통합한다. Merge는 별도 지시를 기다린다.

## PR 초안

제목: **Gmsh 기반 BRL 표면 메쉬 생성기 재작성**

공통 설정·생성·검사·출력 코어를 도입해 ONELAB과 CLI에서 현재 조건의 1차 삼각형 표면 메쉬를 생성하고 검증된 NAS 한 건을 발행합니다. native plate·ogive D/L/t와 STEP/IGES/BREP를 지원하며 단위·PID·열린 sheet 기준/solid outward normal을 보존합니다.

- 전역 cap·파장·fallback, 특징별 폭/edge/gap/수동 영역과 전이, 국소 곡률·CAD 편차 feedback 및 자원 검사를 연결했습니다.
- `AnalyseMeshQuality` ICN과 기존 AR·최소각, 별도 topology/방향/기하 검사를 생성·개선·발행에서 사용합니다. 개선 악화는 정확한 rollback 또는 발행 차단으로 처리합니다.
- 현재 mesh를 다시 검사하고 임시 NAS를 독립 pyNastran reader로 읽어 좌표·ID·connectivity·PID를 대조한 후 원자적으로 발행합니다. 실패 시 이번 임시 파일만 정리하고 기존 정상 결과를 보존합니다.
- web UI·서버·viewer·score·조건 비교·제품 보고서/진단 파일을 포함하지 않습니다. 개발 검증 기록은 `docs/stage-*-validation-ko.md`에 있습니다.

검증: 고정 Python/Gmsh 환경의 전체 pytest, native ogive와 26-surface fillet의 기하/재현성, 실제 CLI launcher·FLTK lifecycle, 정상/차단 NAS 및 독립 읽기를 확인했습니다. 최종 정확한 개수·시간·hash는 [6단계 기록](stage-6-validation-ko.md)을 사용합니다.

한계: 시간·메모리는 native 호출 전후의 협력적 검사입니다. 곡면 편차는 유한 표본이며 EM 정확도 보증이 아닙니다. 자동 폭은 직선·단일 loop·볼록 평면에 한정합니다. native ogive는 L>D/2를 지원합니다. UI widget 외관/마우스 시각 QA는 미실행입니다.

## 전달 절차

1. 대상 저장소·배치 경로·기본 branch를 확인하고 최신 상태와 충돌을 검토한다. 사용자가 교체하도록 지정한 기존 mesh generator와 그 전용 파일을 제거하고 무관한 파일은 보존한다. 소스만 전달하며 `.venv`, `.tools`, `.cache`, `outputs`는 제외한다.
2. 의미 있는 로컬 개발 commit을 보존할 수 있는 배치/branch 방식을 정하고 최종 branch를 push한 후 위 범위와 실제 검증을 담은 PR 한 건을 만든다. 대상 배치로 코드가 바뀌면 필요한 검증을 다시 수행한다.
3. Merge는 사용자의 명시적 지시에 따라 merge commit 방식으로 한다.
4. 병합 성공·기본 branch·미병합 commit·사용자 변경·worktree 사용 여부를 확인한 후 해당 작업 branch를 로컬과 원격에서 삭제한다. 실패/미완료면 보존한다.

PR 대상 확정과 merge 지시는 서로 구분한다. 현재 문서는 PR 초안이며 원격 게시·병합 완료 기록이 아니다.
