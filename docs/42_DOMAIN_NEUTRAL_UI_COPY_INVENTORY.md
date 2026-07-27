# Domain-neutral browser copy inventory

- Status: Maintained
- Scope: browser-visible input placeholders, prompts, examples, empty states, and runtime-published
  browser configuration
- Exclusion: the explicitly optional semiconductor seed, its deterministic fixtures, and tests that
  exercise arbitrary catalog vocabulary

## Inventory method

The product surface is inventoried from committed source rather than from a list of remembered
screens:

```bash
rg -n --glob '*.{ts,tsx}' \
  'placeholder=|예:\s|example|Example|샘플|예시' \
  frontend/src --glob '!**/*.test.*'

rg -ni --glob '*.{ts,tsx,json,js}' \
  '\bwafer\b|\bsemiconductor\b|반도체|수율|제조\s*공정|장비,\s*자재,\s*레시피' \
  frontend/src frontend/public \
  --glob '!**/*.test.*' --glob '!**/*.spec.*'
```

`frontend/src/features/DomainNeutralCopy.test.tsx` renders the representative Chat and Knowledge
inputs in CI, asserts their generic wording, and rejects known semiconductor defaults on those
surfaces. The repository-wide source inventory remains the explicit `rg` gate above so optional
seed/test data can be distinguished from product copy rather than hidden by a broad allowlist.

## Reviewed surfaces

| Surface | Input, prompt, example or empty-state intent | Domain-neutral wording rule |
|---|---|---|
| Global and Catalog search | Locate a dataset by name, description, platform or schema | Ask for catalog identity, never a particular industry object |
| Chat | Discover data and ask impact/lineage questions | Use generic customer/order/table questions |
| Knowledge Chat | Ask about relationships in a selected governed knowledge asset | Refer to the selected asset, never assume an industry |
| Knowledge ingestion | Guide extraction intent and schema search | Use generic customer/order/product relationships |
| Registration | Describe or classify a selected table and its fields | Use the selected asset's server data; placeholders stay structural |
| Governance | Find a change target and explain a requested change | Use generic table/schema and integration examples |
| Admin | Find people, roles, systems and governed resources | Use identity or catalog vocabulary only |
| Empty and unavailable states | Explain no results, missing authorization or unavailable providers | State the actual server/UI state without demo-domain language |
| Runtime-published browser config | Origins, capability flags and provider availability | Contains no catalog-domain example strings |

## Replacements and deliberate exclusions

- Chat default question: `고객 주문 데이터는 어떤 테이블에 있나요?`
- Knowledge extraction intent:
  `고객, 주문, 상품 간 관계를 중심으로 노드를 추출해 주세요.`
- The optional `semiconductor` seed, local-only Airflow seed DAG, seed documentation and test
  fixtures remain unchanged. They are opt-in test data and are not product defaults.
- Tests may continue to use wafer/yield values to prove arbitrary-domain search and highlighting.
  The CI guard intentionally excludes test files while rejecting those values in published browser
  source.
