# 02_BRL_mesh_generator 작업 지침

- 현재 사용 흐름·기본값·범위는 `docs/mesh-generator-guide-ko.html`, 개발 근거·환경·이력은 `docs/validation-ko.md`를 따른다. 문서와 코드를 함께 갱신한다.
- 기존 `99_archive/BRL_2026-10-19`는 읽기 전용 보관 자료다. 기존 runtime을 import하거나 보관된 환경·캐시에 의존하지 않는다.
- Strict schema를 유지한다. 과거 입력·Action·보고서 구조의 호환 계층을 기본으로 추가하지 않고 미지원 입력을 명확히 거부한다.
- Gmsh CAD/mesh API·size field와 `AnalyseMeshQuality` ICN을 사용한다. 사용하지 않는 Jacobian·IGE는 켜지 않는다. Plugin/API의 의미·수치가 같다고 가정하거나 실패 시 조용히 대체하지 않는다.
- 현재 표면 요소에 `DimensionOfElements=2`, `Recompute=1`을 명시한다. 결과 element ID 전체 대응·유한 양의 값·이번 view만 정리·기존 visibility 보존을 확인한다.
- AR≤3·최소각≥20° 정책을 임의 ICN 하한으로 환산하지 않는다. Topology·예상 경계·solid outward/sheet 기준 법선은 별도 검사한다.
- 개선의 연결·ID·PID·entity·경계 node/parameter 불변량과 품질·기하·크기·활성 편차 비악화를 보존한다. 후보 거부는 정확한 rollback 또는 발행 차단으로 처리한다.
- CAD·설정·field·경계 참조가 바뀌면 재생성을 요구하고 현재 메쉬를 재검사한다. 발행은 임시 NAS·독립 pyNastran 읽기·좌표/ID/connectivity/PID 대조 후 수행한다.
- 단위·의도한 열린 경계·분리 gap을 보존한다. 요청 길이와 실제 edge 길이, 기하 검사와 EM 정확도, 협력적 자원 검사와 hard cap을 구분한다.
- 제품 범위에서 score·등급·보고서·독립 진단·웹 UI·비교 생성은 제외한다. 개발 문서·테스트 기록과 제품 출력을 구분한다.
- 테스트·환경·캐시·중간 산출물은 로컬에서 생성한다. 클라우드 폴더는 읽기 전용 source 또는 검증된 최종 deliverable 전달에만 사용한다.
- Commit·PR 제목/본문·검증 설명은 한글로 작성하고 기술 용어/API는 영문을 유지한다. 무관한 사용자 변경을 포함하지 않는다.

## GitHub와 작업 권한

- 사용자 지정 저장소는 `https://github.com/BRL-AIML-students/BRL_AI_EM_convergence.git`, 새 모듈 경로는 `02_BRL_mesh_generator/`다. 이후 수정·PR은 이 저장소를 사용한다.
- Merge와 작업 branch 삭제는 기본적으로 사용자가 직접 한다. 다만 2026-10-20 사용자가 guide의 PR·merge까지 명시적으로 요청했으므로 이번 문서 PR은 Codex가 merge commit으로 병합한다. Branch 삭제는 요청하지 않았으므로 수행하지 않는다.
- 로컬에서 변경·검증한 뒤 요청된 PR을 작성/갱신한다. 문서 설명·로컬 저장 요청만으로 원격 게시를 자동 실행하지 않는다.
- 독립 source 이력과 게시 이력은 parent/SHA가 다르다. Source branch를 원격에 강제 push하지 않는다. 상세 경로·PR 기록은 `docs/validation-ko.md`의 GitHub 절을 먼저 확인한다.
- `.cache/github-delivery`는 별도 Git checkout이다. 이 경로를 포함한 cache 전체를 무심코 삭제하거나 .git/가상환경을 이동하지 않는다. 이번 guide 작업은 구조 이동을 포함하지 않는다.
- 활성 작업의 모델을 유지한다. 외부 모델 위임·과금·reset credit 소비를 자동으로 하지 않는다.
