# Knowledge Phase 6 cutover QA remediation

- 기준일: 2026-07-28
- 필수 DB revision: `0062`
- 범위: Phase 6 Cutover 이후 실사용 QA 6건의 local-source 보완
- 상태: **소스/계약 검증 완료; 대상 PostgreSQL·인증 브라우저·준비 PC 증거는 open**

## 구현 결과

1. 기본 업무 도메인은 Workspace UUID와 고정 slug로 결정적 UUID를 생성한다. `0062`는 기존
   Workspace에 `General`, `Data Governance`, `R&D`, `Finance`, `Space System`을 시딩하고,
   local identity bootstrap은 catalog 권한을 확대하지 않고 같은 결정적 ID를 사용자 domain
   scope에 기록한다. `/knowledge/domains`는 DB 결과가 비어 있을 때에도 Subject domain scope를
   완화하지 않은 채 허용된 기본값만 반환한다. 선택된 fallback은 Draft FK 기록 전에 app-role
   경계를 통해 동일 vocabulary row로 insert/reactivate된다.
2. Registry, Knowledge Chat, Studio는 하나의 `KnowledgeWorkspacePage` 아래에서 SPA
   sub-routing된다. 공통 `Versioned Knowledge Asset Management / 지식관리` PageTitle과 좌측
   작업 메뉴는 유지되고, 종전 Studio 보안 key remount와 메뉴별 top-level lazy remount는
   제거됐다.
3. Registry 상세 drawer 기본 폭은 `min(48vw, 672px)`이며 작업 콘텐츠 좌측 경계까지로 최대
   폭을 제한한다. 좌측 separator는 pointer drag와 키보드 좌/우 화살표를 지원하고 viewport
   resize 시 폭을 다시 clamp한다.
4. 편집은 `asset_id` route를 idempotent
   `POST /knowledge/studio/drafts/from-asset/{asset_id}`로 변환한다. 작성자의 live EDIT Draft가
   있으면 재사용하고, 아니면 active Studio/ontology/instance release를 pin하여 T-Box와 A-Box
   mapping을 Draft child row로 복사한다. 삭제 UI는 실제 삭제 대신 `If-Match`와
   `Idempotency-Key`를 요구하는 `POST /knowledge/graphs/{graph_id}/archive`를 호출한다.
   Archive는 actor/reason outbox evidence를 남기고 immutable releases를 보존한다.
5. version history는 Version, Status, Creator, Created At, Action 열을 가진 표다. active
   instance release에는 `CURRENT` badge가 표시되고, 임의 과거 release를 선택하면 동일
   release ID로 metadata counts/creator/time과 React Flow snapshot을 함께 갱신한다.
6. Registry/Chat/Studio 메뉴 전환은 `history.pushState`와 기존 query router를 사용한다.
   AppShell과 Knowledge workspace shell은 유지되고 콘텐츠만 전환된다.

## 로컬 검증 증거

- Frontend: TypeScript strict PASS, ESLint zero-warning PASS, Vitest
  `56 files / 312 tests` PASS, Vite production build PASS
- Backend: Ruff format/lint PASS, strict mypy `222` source files PASS, pytest
  `1,726 passed / 97 skipped`, `scripts/verify_static.py` PASS
- Schema: sole Alembic head `0062`; canonical `0001` repeated SHA-256
  `7f4e1d543f9eab64d7d03ce503c7ec5306af140cbecd846240b1227033e5bd70`

## 남은 대상 환경 게이트

환경 설정이 필요한 97개 PostgreSQL/S3 integration test는 실행되지 않았다. 실제
`0061 -> 0062` migration, app-role RLS positive/negative, authenticated browser에서 mouse
resize/focus restore/Registry↔Chat 무깜빡임, 준비 PC의 API/Web/OIDC health는
`prep-update` 후 별도 증거가 필요하다. 이 문서는 local-source 통과를 production
acceptance로 승격하지 않는다.
