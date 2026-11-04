# BRL mesh generator 개선 결과 — 2026-11-03

기준 소스는 `4659b8b252c56dc27661cf87ce8f52137026ec4a`다. 최초 점검은 [검토결과.md](../.cache/audit-20261102/검토결과.md), 20개 항목별 구체적인 상태는 [IMPLEMENTATION.md](../.cache/audit-20261102/IMPLEMENTATION.md)에 보존한다. 이 문서는 당시 검토를 덮어쓰지 않는 개선 후 기록이다.

## 2026-11-04 최종 회귀 및 대표 측정

최종 제품 source hash `436ba81d7e29ee3944981754ca7971d5f0f97b4e75ea4e3ddf650d58d3f7dc6d`가 불변인 상태에서 전체 회귀 **548 passed / 679.76초 / exit 0**을 확인했다. 증거는 `.cache/audit-20261102/optin-final.log`, XML, exit 및 source-hash 파일이다. 대상 74건·19건·38건은 별도 단위/대상 시험이다.

다음은 기존 entity 방식과 local 방식의 두 사례 비교다. 각 pure 실행 3회 중앙값이며 측정 여건과 형상에 한정한다. 편차 ratio는 표본 편차를 허용값으로 나눈 값이며, 두 local 결과 모두 이 표본 조건을 통과했지만 기준보다 편차가 크다.

| 사례 | 시간 entity → local | triangles entity → local | 영역 밖 triangles entity → local | 표본 편차 ratio entity → local | 최소각 entity → local | 최대 AR entity → local |
|---|---:|---:|---:|---:|---:|---:|
| local-bend | 18.175 → 16.552초 (−8.93%) | 440 → 354 | 112 → 51 | 0.446 → 0.620 | 30.90° → 32.27° | 1.960 → 1.709 |
| sphere | 1.708 → 1.615초 (−5.42%) | 966 → 786 | 해당 없음 | 0.441 → 0.855 | 37.35° → 21.27° | 1.630 → 2.874 |

구의 local 결과는 품질 조건은 통과했지만 최소각과 최대 AR의 여유가 줄었다. 16회 실행(각 pure 3회와 계측 1회, 두 방식·두 사례)에서 전체 계약·독립 NAS 검증·제품 source hash 일치를 확인했다. 계측 실행은 시간 중앙값에 포함하지 않았다. 두 사례의 속도나 표본 편차로 모든 CAD의 성공, 일반적 속도 향상 또는 EM 정확도를 보장하지 않는다. 원자료는 `.cache/performance/local-curvature-optin-20261104/results.json`과 `.cache/audit-20261102/final-measurement-summary.json`이다.

실제 FLTK API 주입 실행은 fresh process에서 작은 판 44개와 큰 판 55,560개 삼각형을 각각 한 번 성공했다. 큰 판의 observer 제외 event-pump 진입 간격 최대 208.43 ms, loop body 최대 144.98 ms이며 adopt 94.34 ms, 첫 명시 draw 36.33 ms, helper 17.17 ms, main commit 1.35 ms였다. 단계는 중첩될 수 있고 이전 UI와 비교한 수치가 아니다. 마우스 입력·첫 픽셀·GPU 완료·모든 환경의 최대 멈춤은 측정하지 않았다. 같은 프로세스에서 두 번째 FLTK 초기화 시 access violation이 발생했으나 별도 새 프로세스의 큰 판은 성공했으며 원인은 확정되지 않았다. 개발 probe는 한 프로세스에 한 사례·한 번만 허용한다. 원자료는 `.cache/performance/native-fltk/`의 `optin-fltk-20261104-tcuwv9uf/results.json` 및 `optin-fltk-large-fresh-20261104-q6ztbbp8/results.json`이다.

HTML 시각 QA는 Chrome headless 실행 실패와 IAB file URL 정책 차단으로 미완료다.

## 결과와 검증

S2는 `mesh.curvature.feedback`의 기본값 `entity`를 유지하고 `local`을 명시 선택할 때만 위반 표본 주위 크기장을 적용한다. 기존 편차·품질·독립 NAS 검증은 유지하며 실패 시 차단한다. O5는 NAS 복사·hash를 helper thread에서 수행하고 main thread에서 현재성을 재확인해 확정한다. 변경된 임시 경로와 외부 추가 파일은 보존하고 정리 실패를 경고한다. Provenance는 schema 3이다. 곡률 관련 대상 74건(291.744초), 정리·소유권 19건, 설정·provenance·UI 38건이 통과했다. 최종 전체 회귀 548건이 통과했고 대표 성능 측정의 조건과 한계는 아래에 기록했다.

- 형상 교차·공면 중첩 및 일부 비공유 점 접촉 검사, 활성 background field 변경 감지, output_dir만 변경한 재발행, 국소 척도 품질 계산을 보완했다. 검사는 부동소수점 기반이며 연속 기하의 정확한 증명이 아니다.
- 검사 내부 일부 배열과 같은 곡률 투영 표본을 재사용하고, NAS 자체 검사를 streaming으로 전환했다. 독립 pyNastran의 ID·좌표·연결·PID 대조와 발행 직전 검사는 유지한다. 결과는 로컬 검증 후 목적지 복사·hash 대조·확정한다.
- 취소 및 제한적 이전 scene 보존, 종료 미확인·임시 정리 실패 표시, 품질 재생성 opt-in, 곡선 표본화의 수치 정밀도 소진 차단, 단일 NAS provenance를 추가했다. 재생성 성공률을 실제 CAD에서 정량 평가하지 않았다.
- S2/O5 확장 전 S1/O3 전체 회귀는 **513 passed, 385.88초(exit 0)**다. 실행 전후 소스 hash가 같았다. 이 결과가 모든 입력의 정확성이나 외부 EM 해석 수렴을 보장하지는 않는다. 로컬 시험 결과: [retry-local-final.log](../.cache/audit-20261102/retry-local-final.log).

## 사용 시 달라진 점

1. 새 생성에서 품질만 실패했을 때 대체 알고리즘을 시도하려면 JSON의 `generation.quality_retry`를 `delaunay`로 명시하거나 ONELAB의 대응 설정을 사용한다. 기본은 `none`이다. 개선이 정상 반환되고 비형상 검사와 ICN이 통과한 shape-only 실패에만 Algorithm 6 이후 Algorithm 5를 한 번 요청한다. Action 3/4의 현재 mesh는 재생성하지 않으며 Gmsh generate 자체 예외도 재시도하지 않는다.
2. `Cancel current job`은 창을 유지한다. 이전 scene은 설정·CAD·field·경계·검사된 mesh가 확인될 때만 유지한다. 결과를 가져오며 Gmsh가 바뀐 뒤에는 복원을 보장하지 않는다. worker 종료를 확인할 수 없으면 새 작업을 막고 재시도를 요구한다.
3. 발행 NAS의 provenance 주석에는 output_dir을 제외한 유효 설정, 파일 CAD hash, 제한된 소스 범위 hash, base commit과 해당 범위의 Git dirty 상태, 버전과 요청 옵션이 기록된다. Base commit은 현재 실행 코드가 그 commit과 정확히 같다는 뜻이 아니다. 실제 내부 알고리즘·thread와 개선 이력은 확인할 수 없으면 unknown이다. 파일 hash는 원자적 실행 코드 snapshot이 아니다.
4. 출력 위치만 변경하면 현재 mesh를 다시 검사한 뒤 새 위치에 발행할 수 있다. 최종 NAS가 확정된 뒤 임시 정리에 실패해도 발행 성공과 경로를 유지하고 경고를 표시한다. CLI 성공 stdout은 `status`와 `nas_path`이며 경고는 stderr다.

## 시간과 메모리: 측정한 범위

아래 시간·메모리는 S2/O5 확장 전 S1/O3 시점의 측정이다.

| 전체 생성부터 NAS 발행 | 기준 중앙값 | S1/O3 당시 중앙값 | 기준 대비 |
|---|---:|---:|---:|
| 판, 14,038 triangles | 1.849초 | 2.524초 | +36.48% |
| 곡률 구, 4,872 triangles | 8.446초 | 8.787초 | +4.03% |

각 사례를 profiler 없이 세 번 순차 실행했고 외부 부하와 파일 cache는 통제하지 않았다. 두 사례의 node·triangle 수와 주석 제외 NAS mesh card SHA-256은 기준과 같았다. 추가 검사 등을 포함한 현재 전체 작업은 이 두 사례에서 기준보다 오래 걸렸다. 세부 자료: [retry-local-comparison.json](../.cache/audit-20261102/retry-local-comparison.json).

합성 fan mesh에서 NAS 자체 검증을 별도 프로세스로 한 번씩 측정한 결과는 다음과 같다. 메모리는 Windows **프로세스 생애 최대 working set**이며 import·mesh 구성 등의 비용을 포함한다. 이는 Python tracemalloc이나 검증 단계만의 peak가 아니다.

| triangles | 검증 peak 기준 → 현재 | 검증 시간 기준 → 현재 |
|---|---:|---:|
| 10,000 | 112.559 → 107.145 MiB | 0.198 → 0.195초 |
| 100,000 | 327.742 → 269.031 MiB | 2.197 → 2.122초 |
| 1,000,000 | 2,441.297 → 1,872.336 MiB | 23.447 → 22.374초 |

100만 요소 검증 process peak는 이 한 사례에서 약 23.3% 낮았다. 별도 hash 프로세스 peak는 92.680→24.387 MiB였다. 독립 pyNastran을 유지했고, 직접 NAS writer는 provenance를 생략했다. Hash는 native worker의 이전 `read_bytes`와 현재 `file_digest` 연산을 모사하며 worker transport 전체는 측정하지 않았다. 단회 합성 입력이며 외부 부하·cache를 통제하지 않았으므로 실제 CAD나 일반적인 성능을 보장하지 않는다. 로컬 원자료: [10k/100k](../.cache/audit-20261102/nas-memory-10k-100k.json), [1m](../.cache/audit-20261102/nas-memory-1m.json).

## Native 단계의 제한적 측정

판과 곡률 구에서 새 생성·발행과 현재 mesh 발행을 각각 세 번씩 headless 측정했다. 초기화/adopt/NAS 전달의 중앙값은 판 생성 0.0083/0.0367/0.0090초, 판 재발행 0.0441/0.0478/0.0097초, 구 생성 0.0082/0.0269/0.0088초, 구 재발행 0.0315/0.0222/0.0090초였다. Worker 대기는 각각 3.657/2.518/9.763/7.044초이며 초기화와 시작이 겹칠 수 있다. 모든 12건이 성공했고 사례별 NAS hash가 일치했다.

이 측정은 실제 FLTK 창·render·event pump를 포함하지 않으므로 UI 멈춤 시간을 보여주지 않는다. 추가 전체 mesh/독립 NAS probe 검사는 위 단계 시간에 포함되지 않는다. 이 수치는 O5 비동기화 전 측정이며 대형 CAD는 측정하지 않았다. 로컬 원자료: [native-stages-summary.json](../.cache/audit-20261102/native-stages-summary.json).

## 남은 범위

- **부분 구현:** 검사 자료 공유, 교차 BVH와 국소 크기 감사, NAS 메모리, 품질 재생성, 무진전 감지, 이전 scene 복구, 오류 상세, provenance 및 회귀·성능 기준은 일부 범위를 구현했다. 전체 topology 배열화·대형 실제 CAD·peak memory·UI 지연 등은 별도 검증이 필요하다.
- **미구현 연구·확장:** 적응/양방향 CAD 편차 검증, 복잡한 neck·gap·다중 재료 interface, 외부 EM solver를 이용한 관측량 수렴, UI adopt/render 지연 최적화는 수행하지 않았다. 알고리즘 재생성의 실제 CAD 성공률, 대형 assembly, EM 정확도 또한 검증하지 않았다.
- 각 20개 항목의 세부 범위와 남은 일은 [IMPLEMENTATION.md](../.cache/audit-20261102/IMPLEMENTATION.md), 사용자 조작과 한계는 [사용 안내](mesh-generator-guide-ko.html), 상세 이력은 [검증 기록](validation-ko.md)를 참조한다.


## 20개 점검 항목 상태

| 항목 | 상태 | 범위 / 남은 일 |
|---|---|---|
| R1 교차 sheet | 제한적 구현 | BVH 교차·공면 중첩 및 비공면 비공유 점 접촉 검사. 회전 판·공유 경계·양의 gap 대상별 시험 통과. 부동소수점 증명 아님. S2/O5 확장 전 전체 회귀 통과. |
| R2 background 선택 | 구현 | 빈 field 목록의 미등록 활성 ID까지 직렬화로 대조; 대상별 시험 통과. 직렬화 성능 측정 필요. |
| R3 출력 위치 | 구현 | output_dir만 변경 시 재검사 후 발행; 작업 중 변경은 차단. 대상별 시험 통과. |
| R4 국소 척도 | 구현 | 요소별 edge 척도 사용, 대상별 시험 통과. |
| O1 검사 자료 공유 | 제한적 구현 | 검사 단위 read-only XYZ/cross/magnitude를 shape·normals·geometry에서 공유. 재검사 유지, topology 전체 공유 및 성능 확인은 남음. |
| O2 CAD 투영 재사용 | 구현 | 동일 entity·batch의 정확히 동일한 표본만 재사용, 대상별 시험 통과. |
| O3 대규모 자료 구조 | 제한적 구현 | 교차 BVH 순회와 4개 이상 curve query의 bounded midpoint 재사용 구현. 대표 width local audit 약 26% 감소·exact ratio, 작은 사례 이득 없음. topology 배열화·대규모/peak memory 검증 미완료. |
| O4 NAS 메모리 | 제한적 구현 | streaming 및 hash와 reader 전 해제 완료; 합성 100만 요소 단회 측정 완료. worker 경계 JSON 전송 최적화와 실제 CAD 대규모 평가는 미완료. |
| O5 UI 잔여 지연 | 제한적 구현 | NAS 복사·hash는 helper thread, 최종 현재성 확인·rename은 main thread. 소유권·취소·정리 19건 통과. 실제 FLTK 판 사례 각 1회 측정; 사용자 입력과 대형 실제 CAD는 미측정. |
| S1 알고리즘 재시도 | 제한적 구현 | opt-in shape-only 실패 시 새 생성에서 6→5 한 번; current action과 generate 예외 재시도 없음. 주입 및 S2/O5 확장 전 전체 회귀 통과, 실제 CAD 성공률 미측정. |
| S2 국소 곡률 feedback | 제한적 구현 | 기본 entity, local 명시 선택 시 위반 표본 주변 크기장 적용. 기존 검증 유지·실패 시 차단, 곡률 관련 74건 통과. 모든 CAD에서 성공을 보장하지 않음. |
| S3 무진전 | 제한적 구현 | 거부된 동일 개선 반복과 curve sampling의 수치 정밀도 소진을 감지. 기존 표본·spacing·chord 조건 유지, plateau 단독 중단 및 임의 상한 없음. 기하 충돌 조기 진단 미구현. 최종 sampling 대상 시험 15건 통과. |
| S4 실패 복구 | 제한적 구현 | 취소와 사전 검증된 이전 scene 보존, 종료 미확인 시 새 작업 차단·Close 재시도 및 정리 오류 격리. adopt 중 변경 후 복구는 보장하지 않음. |
| V1 편차 검증 | 미착수 | 적응 표본·양방향 검사 별도 검토. |
| V2 CAD 지원 확장 | 미착수 | neck/gap/interface 정책 필요. |
| V3 EM 수렴 | 미착수 | 실제 solver 및 검증 입력 필요. |
| D1 실패 정보 | 제한적 구현 | 형상 최대 AR·최소각·위반 수 및 일부 교차 ID 제공. 모든 검사·단계 정보는 미구현. |
| D2 NAS 재현 정보 | 제한적 구현 | canonical NAS provenance schema 3과 strict hash/설정 검증. 실제 알고리즘·스레드·개선 이력은 unknown, 디스크 코드 hash는 원자적 실행 snapshot이 아님. schema 2 시점 S1/O3 전체 회귀 513건 통과. |
| D3 회귀·성능 기준 | 제한적 구현 | S2/O5 확장 전 전체 회귀 513건, 3회 순차 비교 및 합성 100만 요소 메모리 단회 측정. 최종 전체 회귀 548건 통과 및 대표 두 사례 측정; 실제 대형 CAD 평가는 미완료. |
| D4 로컬 검증·전달 | 구현 | 로컬 stage 검증 후 목적지 복사·hash·rename, 실패 정리 및 확정 후 cleanup 경고 보존 대상별 시험 통과. CLI 성공 stdout 2키, 경고 stderr. |

위 표는 현재 구현·검증 범위의 요약이다. 상세 원자료와 일시적 로그는 이 로컬 작업 공간의 `.cache/audit-20261102`에 있으며, Git에 포함되는 영구 문서가 아니다.
