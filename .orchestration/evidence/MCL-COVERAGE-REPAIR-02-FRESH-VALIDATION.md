# MCL-COVERAGE-REPAIR-02 신선 독립 검증 증적

- **Task ID:** `task_1a8d4b259b6c`
- **역할 / 실제 모델:** `50_QUALITY_VALIDATION` / `gpt-5.6-sol xhigh controlled fallback`
- **검증 시작 HEAD / exact base:** `ce491fbe16442b81815cb8e4c03dfb70d65e89c9`
- **Repair product SHA:** `bb69d89751a0f0c95cb7981f7b9bcec56cda2d90`
- **Repair base SHA:** `97255432eee002620d1be2828462ddf1d51ccdf4`
- **환경:** Darwin arm64, Node `v25.9.0`, npm `11.12.1`, 2026-08-15 KST
- **권한 계약:** `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`; evidence `git add`/`git commit` 사전 승인
- **판정:** **PASS_LOCAL_SOURCE**
- **제품/source write:** **NONE**

## exact diff, fixture, ancestry 검증

- ancestry는 `97255432eee002620d1be2828462ddf1d51ccdf4 -> bb69d89751a0f0c95cb7981f7b9bcec56cda2d90 -> ce491fbe16442b81815cb8e4c03dfb70d65e89c9`의 direct-parent 선형 관계다.
- repair product diff는 정확히 `frontend/poc-mcl-capture.test.mjs` 1파일, `2 insertions(+), 1 deletion(-)`이다.
- fixture는 `valid`를 복사한 `withoutNativeDataType`에서 `delete withoutNativeDataType.nativeDataType`을 실행한다. 따라서 negative fixture의 `nativeDataType` own property는 실제로 absent이고, 기존 malformed 입력 배열과 `assert.throws`가 그대로 검증한다.
- product 이후 `ce491fb`는 기존 builder evidence/receipt 두 파일만 추가한 docs-only commit이다.
- repair product diff에 `frontend/package.json` 및 `frontend/package-lock.json` 변경은 없다.
- fresh `npm ci` 전후 SHA-256은 동일하다.
  - `frontend/package.json`: `d41aa826a203243509e7684eb45a733c7b24a26df0dcf4a0145f05e256d83789`
  - `frontend/package-lock.json`: `534d792566f0e9371ca1c7ca7166acbbdcc801f07146450ff54005b188a28be5`

## 실행 결과

| 검증 | 결과 |
| --- | --- |
| `npm ci` | PASS — 370 packages 설치, 371 packages 감사, 0 vulnerabilities |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS — 27/27 |
| `npm run lint` | PASS — exit 0, `eslint . --max-warnings=0` |
| `npm run typecheck` | PASS — exit 0, `tsc -b --pretty false` |
| exact direct-parent ancestry | PASS |
| repair product 1-file allowlist 및 fixture 확인 | PASS |
| package/lock diff 및 설치 전후 hash | PASS — unchanged |
| `git diff --check` 및 evidence 작성 전 clean 확인 | PASS |

## 계약 경계

- build, server, catalog 및 UI 검증은 반복하지 않았다: **NOT_EXECUTED_BY_CONTRACT**.
- DB/Kafka/DataHub runtime, PREP, OPS, container/service mutation은 수행하지 않았다.
- 제품/source finding repair, 기존 evidence/receipt 수정, push 및 merge는 수행하지 않았다.
- 이 판정은 exact candidate의 요청된 local source gate에만 해당하며 runtime/PREP/OPS 결과를 주장하지 않는다.
