# CHANGE-HIST-T06A REPAIR-02 lint 보수 증거

## 범위와 provenance

- 작업: `task_20eeb139695e`
- dispatch: `ctx_f91b851d9631`
- 역할: `30_IDENTITY_ACCESS repair builder`
- 위험 표기: `R3 REPAIR-02`이며 gate 승인 또는 위험 등급 완화가 아님
- exact base SHA: `7dc5502425fa22a67cb0b94bb60f0a639053d094`
- product commit: `7da591b55a43e01beca5ca9c9e38d8993105db17`
- 제품 변경 경로: `frontend/poc-server.mjs`, `frontend/poc-server.test.mjs`
- package/lock SHA-256: `f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`, `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- 승인 상태: `G1-G4 NOT_APPROVED`

시작 시 HEAD는 요구된 exact base와 일치했고 작업 트리는 clean이었다. 독립 검증에서 보고된 lint
세 건만 보수했으며 dependency, lockfile, ESLint 설정·disable 주석, validator 계약, schema, service,
UI, T06B는 변경하지 않았다.

## 보수 내용

`accessString`과 `accessOptionalString`에 중복되어 있던 control-character 정규식 두 개를
`hasAccessControlCharacter` 한 함수로 교체했다. 이 함수는 문자열을 Unicode code point 단위로
순회하고 code point가 `0x00` 이상 `0x1f` 이하이거나 정확히 `0x7f`일 때만 `true`를 반환한다.
따라서 기존 금지 범위 `U+0000-U+001F`, `U+007F`는 그대로이며 그 밖의 code point, 길이 제한,
trim, 빈 문자열, 오류 코드와 오류 문구는 바뀌지 않았다.

테스트 전용 `structuredClone(afterGeneric.changeRecords)`는 plain JSON fixture에 적합한 명시적
`JSON.parse(JSON.stringify(...))` deep clone으로 교체했다. production의 `structuredClone` 사용과
동작은 변경하지 않았고, access 갱신이 기존 CR 배열에 zero effect임을 검증하는 테스트 의미도
유지했다.

## 필수 순차 검증 결과

`frontend/node_modules`가 없어서 기존 exact lockfile로 `npm ci --no-audit --no-fund`를 실행해
368 packages를 설치했다. package/lockfile 추적 변경은 없었다. 최종 gate는 코디네이터가 NVM
Node `v25.6.1`, npm `11.9.0` 비-PTY 환경에서 아래 요구 순서로 재검증했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `node --test poc-state-store.test.mjs` | `PASS`, 11/11 |
| 2 | `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk warning만 존재 |
| 3 | `node --test poc-server.test.mjs` | `PASS`, 12/12 |
| 4 | `npm run lint` | `PASS`, exit 0, warning 0 |
| 5 | `npm run build:poc` | `PASS`; 동일한 기존 chunk warning만 존재 |
| 6 | `npm run test:poc-server` | `PASS`, 31/31 |
| 7 | `git diff --check` | `PASS` |

worker의 Orca PTY 로그인 셸은 한 시점에 NVM 대신 Homebrew Node `v25.9.0`을 선택했고 server test가
종료 대기 상태에 들어가 중단했다. 이어 NVM Node를 명시한 workspace sandbox 진단에서는
`listen EPERM: operation not permitted 127.0.0.1`이 관찰되어 pending test가 취소됐다. 두 실행은
제품 assertion 실패가 아니라 Orca PTY/sandbox 환경 제약이며 최종 gate 증거에서 제외했다. 위
비-PTY Node `v25.6.1` 재검증은 같은 소스에서 focused server 12/12와 전체 POC server 31/31을
통과했다.

## 잔여 범위와 판정

판정은 `PASS_LOCAL_SOURCE`다. PREP, OPS, TARGET, production IAM/RLS/ABAC, 배포 runtime, 실제 provider
연동은 `NOT_EXECUTED`다. push, merge, release와 gate 승인은 수행하지 않았고
`G1-G4 NOT_APPROVED`를 유지한다.
