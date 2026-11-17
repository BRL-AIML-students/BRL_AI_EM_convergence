# 02_BRL_mesh_generator 작업 지침

- 현재 코드 구성·호출 계약은 `docs/01_프로그램구성과사용인터페이스.html`, 변환기 변수·기본값·범위·활성 조건은 `docs/02_설정변수빠른참조.html`, 생성·크기장·품질 평가·개선·재생성 원리는 `docs/03_메쉬생성원리와품질평가.html`을 따른다. 기존 변수 표를 활용하며 예제와 ONELAB UI 사용 설명은 문서 범위에서 제외한다. 개발 검증·변경이력 HTML은 만들지 않는다. 동작·설정을 바꾸면 해당 현재 동작 문서를 함께 갱신한다.
- 메쉬용 주파수는 `mesh_frequency_hz`로 독립 지정하고 MoM 변수에서 읽지 않는다.
- 기존 `99_archive/BRL_2026-10-19`는 읽기 전용 보관 자료다. 기존 runtime을 import하거나 보관된 환경·캐시에 의존하지 않는다.
- Strict schema를 유지한다. 과거 입력·Action·보고서 구조의 호환 계층을 기본으로 추가하지 않고 미지원 입력을 명확히 거부한다.
- Gmsh CAD/mesh API·size field를 사용하고, ICN·IGE 평가는 각각 `quality.icn_enabled`·`quality.ige_enabled`가 켜졌을 때 `AnalyseMeshQuality`로 수행한다. 명시적 품질 색상 표시는 평가 스위치와 별도다. 각 호출에서 요청한 지표 하나만 켜며 사용하지 않는 Jacobian은 켜지 않는다. Radius Ratio는 Gmsh 내장 API `gamma`(1차 삼각형의 정규화된 2r/R)를 사용한다. Plugin/API의 의미·수치가 같다고 가정하거나 실패 시 조용히 대체하지 않는다.
- ICN·IGE 호출 시 현재 표면 요소에 `DimensionOfElements=2`, `Recompute=1`을 명시한다. 결과 element ID 전체 대응·유한 양의 값·이번 view만 정리·기존 visibility 보존을 확인한다.
- ICN·IGE·AR·최소각·radius ratio는 `quality`에서 개별 활성화·기준값을 지정한다. 기본값 AR≤3·최소각≥20°를 임의 ICN 하한으로 환산하지 않는다. Topology·예상 경계·solid outward/sheet 기준 법선·퇴화 요소·독립 NAS 검증은 평가 스위치와 별도로 유지한다.
- 개선의 연결·ID·PID·entity·경계 node/parameter 불변량과 품질·기하·크기·활성 편차 비악화를 보존한다. 후보 거부는 정확한 rollback 또는 발행 차단으로 처리한다.
- CAD·설정·field·경계 참조가 바뀌면 재생성을 요구하고 현재 메쉬를 재검사한다. 발행은 임시 NAS·독립 pyNastran 읽기·좌표/ID/connectivity/PID 대조 후 수행한다.
- 단위·의도한 열린 경계·분리 gap을 보존한다. 요청 길이와 실제 edge 길이, 기하 검사와 EM 정확도을 구분한다.
- 제품 출력은 NAS와 대응 단일 HTML 품질 보고서다. 활성 ICN·IGE·AR·최소각·Radius Ratio의 기준 미달은 경고·보고서로 남기고 NAS 발행을 차단하지 않는다. 구조·연결·법선·퇴화 요소·CAD 보존·필수 측정 및 독립 NAS 검증 오류는 계속 차단한다. 임의 종합 score·등급·EM 정확도 보증·웹 UI·비교 생성은 제외한다.
- 테스트·환경·캐시·중간 산출물은 로컬에서 생성한다. 클라우드 폴더는 읽기 전용 source 또는 검증된 최종 deliverable 전달에만 사용한다.
- Commit·PR 제목/본문·검증 설명은 한글로 작성하고 기술 용어/API는 영문을 유지한다. 무관한 사용자 변경을 포함하지 않는다.

## GitHub와 작업 권한

- 사용자 지정 저장소는 `https://github.com/BRL-AIML-students/BRL_AI_EM_convergence.git`, 새 모듈 경로는 `02_BRL_mesh_generator/`다. 이후 수정·PR은 이 저장소를 사용한다.
- Merge는 명시적으로 요청받은 범위에서 수행한다. 사용자가 merge까지 요청하면 merge commit으로 병합한 뒤 해당 PR의 원격 작업 branch와 대응하는 로컬 작업 branch를 삭제한다. main과 무관한 branch는 삭제하지 않는다. 2026-10-20 사용자가 이 규칙과 UI 수정·native 형상 확장의 일괄 merge를 명시했다.
- 로컬에서 변경·검증한 뒤 요청된 PR을 작성/갱신한다. 문서 설명·로컬 저장 요청만으로 원격 게시를 자동 실행하지 않는다.
- 독립 source 이력과 게시 이력은 parent/SHA가 다르다. Source branch를 원격에 강제 push하지 않는다. 게시 경로·PR 기록은 실제 Git remote·branch·GitHub 이력에서 확인하며 별도 변경이력 HTML에 의존하지 않는다.
- `.cache/github-delivery`는 별도 Git checkout이다. 이 경로를 포함한 cache 전체를 무심코 삭제하거나 .git/가상환경을 이동하지 않는다. 선택 기능은 ui/·builtin_geometry/·development/로 구분하며 공통 CAD 원본에서 최소 배포를 자동 생성한다. ONELAB 실행 BAT만 원본에 유지하고 최소 배포에는 BAT를 포함하지 않는다.
- 활성 작업의 모델을 유지한다. 외부 모델 위임·과금·reset credit 소비를 자동으로 하지 않는다.

- 2026-11-17 사용자가 명시한 병렬 작업에서는 GPT-6.1 Sol이 설계·검토를 맡고 GPT-6.1 Terra가 분리된 구현 작업을 맡는다. 공유 파일 변경을 조율하고 최종 통합 검증은 공통 원본에서 수행한다. 전역 모델 기본값은 변경하지 않는다.

- IGE 기본값은 `ige_enabled=false`, `ige_minimum=0.0`이다. 0은 추가 품질 하한을 요구하지 않는 중립 기준이며 활성 측정의 양수·유한성은 별도로 검증한다. IGE는 Gamma·AR 역수와 구분하며 기준을 임의 환산하지 않는다. Strict NAS provenance는 IGE 설정을 포함한 schema 5이며 과거 schema를 조용히 변환하지 않는다.
