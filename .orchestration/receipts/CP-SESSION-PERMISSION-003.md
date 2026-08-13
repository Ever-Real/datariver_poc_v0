# CP-SESSION-PERMISSION-003

## Receipt (영수증)
- Exact SHA: 8331c92e23452dfbe7aeb9a4d440212fef0686db
- Allowed Paths: PRODUCT_CONTROL.md, .orchestration/policies/command-permissions.md, .orchestration/templates/TASK.md, .orchestration/templates/SESSION.md, .orchestration/receipts/CP-SESSION-PERMISSION-003.md
- Actual Changes:
  - `command-permissions.md`에 지속적 안전 승인(Persistent Safe Approval) 및 세션 부트스트랩(Session Bootstrap) 규칙을 추가하여, 단일 원시 명령어에 대한 좁은 범위의 승인 체계를 구체화했습니다.
  - `SESSION.md` 템플릿을 신규 생성하여 새로운 세션 초기화 시 역할을 명확히 하는 항목들을 정의했습니다.
  - `PRODUCT_CONTROL.md`에 세션 템플릿 사용 요건 및 빌더/읽기 전용 프로바이더 론치(Provider Launch) 정책(agy 명령어 기준)을 명시했습니다.
  - `TASK.md` 템플릿에 런타임 론치 모드, 안전 승인 세트, 단일 원시 명령어 강제 등의 필드를 추가하고 Command Permission Contract를 갱신했습니다.
- Outcome: CONTROL_ACCEPTED

## NOT_EXECUTED
- product mutation
- product tests
- runtime automation
- heartbeat
- push
- merge
- PREP
- OPS
