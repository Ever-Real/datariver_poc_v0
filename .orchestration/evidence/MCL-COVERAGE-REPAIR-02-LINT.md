# MCL-COVERAGE-REPAIR-02-LINT 보수 증적

- **Task:** `MCL-COVERAGE-REPAIR-02-LINT` / `task_8e0e868b2b7f`
- **역할:** `40_DATA_AI_KNOWLEDGE Builder`
- **Exact base SHA:** `97255432eee002620d1be2828462ddf1d51ccdf4`
- **Product commit SHA:** `bb69d89751a0f0c95cb7981f7b9bcec56cda2d90`
- **검증일:** 2026-08-15 KST
- **판정:** `PASS_LOCAL_SOURCE`

## 최소 보수

`frontend/poc-mcl-capture.test.mjs`의 `no-unused-vars` 1건만 수정했다. `valid` fixture를 복사한 뒤 `nativeDataType` own property를 삭제해 `withoutNativeDataType`을 만들므로, negative fixture에는 해당 필드가 실제로 존재하지 않는다. 이 fixture는 기존 malformed 입력 배열과 기존 `assert.throws`를 그대로 통과하며 required `nativeDataType`의 fail-closed 계약을 유지한다.

제품 커밋은 위 테스트 1파일의 2줄 추가/1줄 삭제만 포함한다. 제품 모듈, dependency 선언, `package.json`, `package-lock.json` 및 다른 파일은 수정하지 않았다.

## 실행 증적

| 검증 | 결과 |
| --- | --- |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS — 27/27 |
| `npm run lint` | PASS — exit 0, warning 0 |
| `npm run typecheck` | PASS — exit 0 |
| `git diff --check` | PASS |
| 제품 commit allowlist | PASS — `frontend/poc-mcl-capture.test.mjs` 1파일만 변경 |
| exact base 대비 `frontend/package.json` / `frontend/package-lock.json` diff | PASS — 변경 없음 |

이 worktree에는 처음 `node_modules`가 없어 최초 검증 시 dependency 해석 단계에서 중단됐다. `npm ci`로 lockfile에 고정된 370 packages를 설치했고 감사 결과는 취약점 0건이었다. 이후 위 focused test, lint, typecheck를 실효 재실행했으며 모두 통과했다. 설치 전후 package/lock 내용은 변경되지 않았다.

- `frontend/package.json` SHA-256: `d41aa826a203243509e7684eb45a733c7b24a26df0dcf4a0145f05e256d83789`
- `frontend/package-lock.json` SHA-256: `534d792566f0e9371ca1c7ca7166acbbdcc801f07146450ff54005b188a28be5`

## 금지 경계

제품 모듈·의존성·다른 제품 파일 수정, push, merge, DB/Kafka/DataHub/PREP/OPS runtime mutation, service/container 실행은 수행하지 않았다. 기존 evidence/receipt도 수정하지 않았다.
