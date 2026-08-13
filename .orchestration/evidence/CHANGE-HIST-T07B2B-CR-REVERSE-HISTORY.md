# CHANGE-HIST-T07B2B · CR 역방향 변경 이력

## 결과

- 기준 커밋: `3b2ad95efdab74be361b3c1663728929ba55ae66`
- 제품 커밋: `c87df404645b62e0a79ba41f99486c403ba92abb`
- 변경 범위: `ChangeRequestDetailDialog.tsx`, `GovernancePage.test.tsx`
- CR 상세가 열려 있고 정확한 상세 `value`가 있을 때만 `ChangeHistoryApi.reverseHistory(value.id, { limit: 50, signal })`를 호출한다.
- 이력의 loading/error/empty/data 상태는 CR 상세 상태와 분리했다. 거부·404·오류가 발생해도 CR 다이얼로그와 기존 상태·전이·revision·승인·첨부·action 흐름은 유지된다.
- 닫기 또는 CR ID 전환 때 `AbortController`, 요청 intent, 현재 ID fence로 stale 응답 채택을 차단한다.
- 서버가 반환한 최대 50건만 읽기 전용으로 표시한다. `source_occurred_at`을 KST로 표시하고 없으면 `detected_at` 대체임을 명시한다. category/operation, asset/entity, current stage/current primary를 함께 표시한다.
- mutation UI/API, 로컬 집계·권한 필터, provider 조회는 추가하지 않았다.

## 검증

- `npm ci --offline`: 통과, 취약점 0건
- `npm test -- --run src/features/governance/GovernancePage.test.tsx`: 통과, 30/30
- `npm run lint`: 통과
- `npm run typecheck`: 통과
- `npm run build:poc`: 통과
- `git diff --check`: 통과
- 제품 커밋 경로 검사: 허용된 제품 파일 2개만 포함

## 승인 상태

- G1: NOT_APPROVED
- G2: NOT_APPROVED
- G3: NOT_APPROVED
- G4: NOT_APPROVED

런타임·provider·DB·PREP·OPS·TARGET 작업과 push/merge는 수행하지 않았다.
