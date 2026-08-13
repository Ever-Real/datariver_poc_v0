# CHANGE-HIST-T06A F-01 보수 영수증

- task: `task_530e80f9912a`
- dispatch: `ctx_5ed48ab83102`
- exact base: `4e73807539b43be681a2b96a2e355195c6397883`
- source product commit: `d297369774ca6434263ab3ec2d97dd37bb34c123`
- 상세 evidence: `.orchestration/evidence/CHANGE-HIST-T06A-REPAIR-01.md`
- evidence SHA-256: `8d07865f0907a5d44fb50dff11cbfe4e776345d74bbbd817d1b2f7d878586321`

두 PostgreSQL write transaction이 `BEGIN` 직후 동일
`pg_advisory_xact_lock(hashtextextended(CHANGE_HISTORY_ACCESS_SCOPE, 0))`을 획득하도록 하여, row가
모두 없을 때 `FOR UPDATE`가 보호하지 못한 최초 access bootstrap/core PUT 경쟁을 직렬화했다.
PostgreSQL double은 양 경로의 `BEGIN < advisory_xact < row SELECT < write`와 stale rollback을
검증한다.

최종 로컬 결과는 state-store 11/11, lint PASS, build:poc PASS, build 후 test:poc-server 31/31이다.
지정 순서상 build 전에 실행한 server 단일 테스트는 `dist-poc` 부재로 정적 응답 1건만 404였고,
build 후 같은 응답을 포함한 전체 suite가 통과했다. 다른 source/설계/dependency/config/service/UI/T06B,
push/merge/PREP/OPS는 없으며 `G1-G4 NOT_APPROVED`다.
