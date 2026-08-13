# 영수증: CHANGE-HIST-T06A-REPAIR-02

## 결과

- 판정: `PASS_LOCAL_SOURCE`
- task: `task_20eeb139695e`
- dispatch: `ctx_f91b851d9631`
- exact base: `7dc5502425fa22a67cb0b94bb60f0a639053d094`
- product commit: `7da591b55a43e01beca5ca9c9e38d8993105db17`
- 변경 범위: `frontend/poc-server.mjs`, `frontend/poc-server.test.mjs`
- 상세 evidence: `.orchestration/evidence/CHANGE-HIST-T06A-REPAIR-02.md`
- evidence SHA-256: `0291f7057eef668355dc89e9dd2601a6c5415a36ef9ec46780555600c744f405`
- 승인 상태: `G1-G4 NOT_APPROVED`

두 access 문자열 validator의 control-character 정규식을 code-point predicate 한 개로 교체해 기존
금지 범위 `U+0000-U+001F`, `U+007F`를 정확히 유지했다. 테스트의 plain CR fixture만 명시적 JSON
deep clone으로 바꾸었으며 production 동작, validator, ESLint/test 설정은 완화하지 않았다.

코디네이터의 NVM Node `v25.6.1`/npm `11.9.0` 비-PTY 재검증은 state-store 11/11, 첫 POC build,
focused server 12/12, zero-warning lint, 두 번째 POC build, 전체 POC server 31/31과
`git diff --check`를 모두 통과했다. 두 build의 기존 500 kB 초과 chunk warning은 비차단이었다.

worker Orca PTY의 Homebrew Node `v25.9.0` 종료 대기와 workspace sandbox의 loopback `listen EPERM`은
제품 assertion 실패가 아닌 실행 환경 제약으로 최종 gate에서 제외했다. dependency/lockfile, config,
schema, service, UI, T06B, push/merge/PREP/OPS/TARGET 변경이나 실행은 없으며 gate 승인을 주장하지 않는다.
