# CHANGE-HIST-T07B2A-WEEKLY-LINK-UI 구현 증거

## 범위와 기준

- Task: `CHANGE-HIST-T07B2A-WEEKLY-LINK-UI`
- exact base: `bdd96fb02762aa8d510ec3021a14212a83c4a125`
- 제품 commit: `5493517466334557c9de57bd15f28a43ff73ff4f`
- 작업 branch/worktree: `Ever-Real/change-hist-t07b2-governance-ui`,
  `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t07b2-governance-ui`
- 제품 변경은 배정된 Governance 다섯 경로에만 한정했다. 기존 중단 빌더가 남긴
  `GovernancePage.tsx`, `DetectedChangeCrPanel.tsx`, `changeHistoryCr.css`의 부분 변경을 reset하지 않고
  이어서 완성했다. Change History API/type/server/dependency/lockfile/전역 CSS와 CR state/workflow는
  변경하지 않았다.

## 구현 결과

1. Governance 화면에 독립 `Detected Change → CR` panel을 추가했다. 현재 KST 날짜의 월요일을 정확한
   `week_start`로 계산하고 server weekly 응답의 전체, CR 미연결, 접수 완료, 재검토, 변경/TEST,
   완료검토, 완료 일곱 count를 그대로 표시한다.
2. 각 count card는 최대 50건의 server event list를 다시 읽는다. 전체는 `week_start + limit=50`,
   CR 미연결은 `week_start + link_state=UNLINKED + limit=50`, 나머지 다섯 단계는 각각 정확한
   `stage=RECEIVED|RECHECK|TESTING|FINAL_REVIEW|COMPLETED`를 사용한다. 브라우저가 count나 권한 결과를
   재분류하지 않는다.
3. 이벤트를 선택하면 event detail과 CR link history를 모두 `no-store`로 다시 읽는다. 두 응답의
   current link-head ETag가 없거나 서로 다르면 mutation control을 열지 않고 fail closed한다.
   mutation selector는 fresh event의 `allowed_link_actions`만 사용하므로 viewer 또는 빈 action 응답은
   controls 자체를 숨긴다.
4. `SET_PRIMARY`/`ADD_CANDIDATE` 대상은 현재 Governance server summary window가 허용한
   `ChangeRequestSummary.id/current_round_number`만 사용한다. `CLEAR_PRIMARY`/`REMOVE_CANDIDATE`는 여기에
   fresh primary/candidate target까지 교차해 과거 round, 숨겨진 CR 또는 임의 ID를 선택할 수 없게 했다.
5. 네 action command body는 `action`, `change_request_id`, `change_request_round`, trimmed `reason`만
   포함한다. 일치 검증한 fresh event ETag를 `If-Match`로, `crypto.randomUUID()`를
   `Idempotency-Key`로 보내며 actor/role/System/time/policy/basis를 생성하거나 전송하지 않는다.
6. 저장 전에 primary/candidate/list/count를 바꾸는 optimistic success가 없다. command 성공 뒤 event,
   links, weekly, 현재 filter의 event list 네 읽기가 모두 성공해야 화면 상태를 한 번에 교체하고 form을
   비운다. stale ETag command 실패는 기존 authoritative 화면과 입력을 보존하고 재조회나 자동 재전송을
   하지 않는다.
7. initial loading, authorized empty, weekly/list error, detail/ETag error, target 없음, saving 상태를 서로
   구분했다. 기존 CR 상세/생성/revision/approval/transition/apply/attachment 흐름은 변경하지 않았고
   `reverseHistory`나 `ChangeRequestDetailDialog` 확장은 포함하지 않았다.

## 검증

환경은 macOS arm64, Node `v25.9.0`, npm `11.12.1`이다. dependency가 없는 worktree에서 최초 focused
test는 `vitest: command not found`로 test body 전에 실행되지 않았다. `npm ci --offline`이 기존
lockfile을 변경하지 않고 368 packages를 설치한 뒤 최종 acceptance 명령을 실행했다.

| 명령 | 결과 |
|---|---|
| `npm test -- --run src/features/governance/DetectedChangeCrPanel.test.tsx src/features/governance/GovernancePage.test.tsx` | `PASS`, 2 files / 41 tests |
| `npm run lint` | `PASS`, warning/error 0 |
| `npm run typecheck` | `PASS` |
| `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check` 및 exact staged allowlist review | `PASS` |

focused test는 일곱 weekly card의 exact `week_start`/`link_state`/`stage`/limit 50, 일곱 server count,
loading/error/authorized empty, viewer/no-actions, event/link ETag 불일치 fail-closed, 네 link action 각각의
current authorized summary/current round target, exact body/If-Match/UUID idempotency, 성공 뒤 네 fresh
refetch, stale failure 시 no optimistic change/no refetch를 검증한다. Governance 기존 25 tests는 child
panel transport를 unit 경계로 격리해 기존 CR state/workflow 회귀를 확인했다.

## 미실행과 gate

- browser runtime 또는 credentialless smoke: `NOT_EXECUTED`
- 실제 provider/DataHub/Timeline/MCL/PostgreSQL probe 또는 mutation: `NOT_EXECUTED`
- container/service/network/volume/process mutation: `NOT_EXECUTED`
- push/merge/PREP/OPS/TARGET: `NOT_EXECUTED`
- 전체 repository test suite: `NOT_EXECUTED` — 배정된 focused Governance acceptance만 실행
- G1/G2/G3/G4: `NOT_APPROVED`

할당된 T07B2A source와 필수 gate에는 blocker가 없다. fresh independent validation이 남아 있으며,
이 제품 commit을 runtime/provider/production 검증이나 release 승인으로 승격하지 않는다.
