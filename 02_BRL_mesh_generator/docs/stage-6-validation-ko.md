# 6단계: native ogive와 통합 검증

2026-10-20, 시작 commit `2c4f9d5`, 작업 branch `codex/rebuild-core`. 새 로컬 프로젝트에서 구현·검증했으며 보관 runtime/env를 import하거나 실행하지 않았다. 원격 저장소는 등록하지 않았고 push·PR·merge·branch 삭제는 수행하지 않았다.

## 구현

- `geometry.kind=ogive`의 `diameter` D, `length` L, `thickness` t, `origin`을 strict schema·CLI·ONELAB에 연결했다. D/L/t/origin은 입력 길이 단위, 목표 길이·허용 편차는 출력 단위다. `R=L²/D+D/4`, generating-circle center `xc=D/2−R`의 정확한 원호를 native OCC 반회전·복사·회전으로 구성한다. STEP 중간 파일이 없다.
- t=0은 fragment로 공유 경계를 가진 두 sheet를 만들고 해석적인 바깥 방향을 기준으로 잡는다. t>0은 반경 R−t의 동심 내측 원호, tip 축 선분, base 선분으로 단면을 닫고 반회전 solid 두 개를 fuse한다. 결과 한 solid의 outward normal은 공통 검사로 확인한다. 생성 center/section을 정리해 독립 helper가 bbox·mesh에 섞이지 않게 한다.
- 지원 범위는 `D>0`, `L>D/2`, `0<=t<D/2`다. L=D/2의 반구 endpoint는 OCC boolean 경로에서 실패해 미지원 입력으로 명시적으로 거부한다. L<D/2를 같은 tangent-ogive로 조용히 해석하지 않는다. 원호 반경·두께·origin과 단위 변환의 정밀도/유한성도 생성 전에 확인한다.
- root만 뒤에 translate하면 Gmsh/OCC의 이전 보조 entity가 원점에 남는 사례를 확인했다. origin 위치에서 원호와 회전축을 직접 구성하고 불필요 entity를 정리하는 방식으로 수정했다. mm/m의 전체 model bbox와 topology를 검사한다.

## Trim 경계 편차 수정

유한 두께 ogive의 base는 annulus다. 내측 원 경계의 mesh chord는 hole 쪽으로 놓일 수 있으므로 underlying plane으로 투영한 점은 CAD trim 밖이다. 이를 곧바로 projection 실패로 처리하던 5단계 경로를 수정했다.

1. surface projection과 parameter round-trip을 확인하고 trim 포함을 batch/point로 일관되게 분류한다.
2. trim 밖 표본은 해당 face의 실제 boundary curve들에 투영하고 유효한 후보 중 가까운 점을 택한다. curve parameter/endpoint 검증은 공통 경로를 사용한다.
3. 선택된 점의 surface parameter·round-trip·trim 포함을 다시 확인한다. 후보 누락·비유한 값·분류 불일치·API 실패는 차단한다. 추가 curve projection도 같은 작업 예산을 소비한다.

평면에서는 trimmed nearest distance다. 일반 곡면에서는 확인된 유효 CAD 점까지의 보수적인 거리이며 전역 최근접점 증명이 아니다. 거리를 작게 가정해 통과시키지 않고 편차에 따라 실제로 재생성/차단한다. 원본 element ID 대응·현재 mesh 재검사·view 정리 계약을 유지한다. 5단계 기록은 당시 상태로 남긴다.

## 검증 결과

환경과 `uv.lock`은 5단계와 동일하다. 전체 회귀 **299개 통과, 318.44 s**, warning 없음. 이전 277개와 native ogive·trim·복잡 CAD 재현성의 새 22개를 포함한다. 이후 양의 t가 단위 변환 underflow로 0이 되어 solid 대신 sheet가 되는 경로를 차단하고 테스트 1개를 추가했다. 관련 단위/입력/trim **19개 통과, 1.62 s**를 확인했으며 최종 수집 대상은 300개다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest --basetemp .cache\tests\stage6-full
```

새 테스트는 실제 native CAD/mesh/NAS, 원호 식과 surface area, 독립 단면 적분의 wall volume, base 열린 경계/단일 solid, outward 방향, helper 정리, 단위/origin, invalid/미지원/정밀도 입력, ONELAB 변경 무효화, hole/외측 trim 거리, 복잡 fillet 반복성을 확인한다.

| 실행 | 실제 결과 |
|---|---|
| `examples/ogive.json` | D=2·L=3·t=0 mm, cap=.7·delta=.02 mm; 388 node / 749 triangle, 독립 NAS 발행 |
| `examples/ogive_wall.json` | D=2·L=3·t=.2 mm, cap=.15·delta=.02 mm; 1367 node / 2730 triangle, 독립 NAS 발행 |
| 두 예제의 CLI 반복·실제 FLTK Action | 각각 전체 NAS bytes 일치; 좌표·ID·connectivity·PID까지 비교. FLTK 5 cycles 후 finalize |
| `.\run_cli.bat examples\plate.json` | 정상 발행, 1–5단계와 동일 SHA256 |
| Plane trim 직접 거리 | 4×4 판의 R=.5 hole 안쪽 점 거리 .1, 외측 점 거리 1, 면 내부 점 거리 0 |
| 복잡 BREP | 26개 surface의 R=.15 fillet solid, cap=.15·delta=.01; 두 번 전체 NAS bytes와 PID·산출물 검증 |

thin ogive node에 대해 `(rho+4)²+z²=25`, 전체 surface area에 대해 `2π(xc R asin(L/R)+R L)`을 확인한다. wall은 outer/inner 회전체 단면의 128점 Gauss–Legendre 적분으로 CAD volume을 독립 비교한다. 기하 검증과 EM 정확도는 구분한다.

### NAS 경로와 SHA256

- thin CLI: `outputs/run_178187e570b64ab2a55009d28a685d27/mesh.nas`, 반복 `outputs/run_99c67670446942ccb731ce049a4cddc3/mesh.nas`. SHA256 `bcfab81b5e86a29a1562d74c9f9a14253bfef93d65b732944f17deea6c0504be`.
- thin FLTK: `.cache/native-smoke/02c4740b24ee473d8e7950cd2ce2c5b3/run_7d0899a5877c404e950d4222283bd385/mesh.nas`.
- wall CLI: `outputs/run_dd96e843b83b4c0389b6bfbc6df241a3/mesh.nas`, 반복 `outputs/run_7baa5a5ad6fc489e9c671f14da5c0fb3/mesh.nas`. SHA256 `3f0f2c34f593d6428e10adc9b1c308d34941679c8543f0cea3dc9a269440ef45`.
- wall FLTK: `.cache/native-smoke/86bb9fd63af448e9b5f295c19be3c57a/run_c77b490f202b47e492cd33ee1ed72a90/mesh.nas`.
- plate launcher: `outputs/run_75ee949cb7d24f7ba7b120538a691623/mesh.nas`, SHA256 `d6b3e6a6973585a96f2bab48d5d20294140a986ed3e029d01262237105dc1a55`.

정상 run은 `mesh.nas` 한 건만 포함한다. 개발 중 차단된 실행에서는 NAS를 발행하지 않았고 기존 결과도 수정하지 않았다. 제품에 web UI·HTTP·viewer·score·비교 생성·보고서/진단 파일 경로를 추가하지 않았다.

## 완료 범위와 남은 항목

로컬 실행 코어와 자동 통합 검증을 완료하고 최종 GitHub 전달 대상으로 준비했다. 마우스/키보드로 widget를 조작하는 시각 QA는 미실행이며 FLTK API-injected Action 검증과 구분한다. 자원 제어는 협력적 검사이며 native 호출 강제 중단/peak memory hard cap이 아니다. 곡면 편차는 유한 표본·단방향 거리이며 임의 CAD의 연속 최대/Hausdorff/전체 face 교차 또는 MoM/RCS 정확도를 보증하지 않는다.

GitHub 저장소·배치 경로·기본 branch를 확정한 뒤 최종 PR을 준비한다. 사용자의 명시적 merge 지시 전에는 병합하지 않는다. 지시에 따른 merge commit 성공을 확인한 뒤 기본 branch·미병합 commit·사용자 변경·연결 worktree를 확인하고 작업 branch만 삭제한다. 기존 접근 제한 캐시/권한은 이 작업에서 변경하지 않는다.

근거: [Gmsh OCC API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002focc), 보관본 `01_mesh_generator/geometry_mesh/ogive.py`의 원호·반회전 구성과 D/L/t 의미를 읽기 전용으로 검토했다. 새 runtime은 이를 import하지 않는다.
