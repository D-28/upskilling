# Property & Differential Test Starters

Copy these minimal starters when verifying parsers, normalizers, or legacy-to-modern migrations (see [`playbooks/verification-engineering.md`](../../playbooks/verification-engineering.md)).

## Patterns Covered
1. **Round-trip:** `decode(encode(x)) == x`.
2. **Idempotency:** `f(f(x)) == f(x)`.
3. **Invariant preservation:** Length, ordering, and threshold guarantees across generated inputs.
4. **Differential harness:** Compare legacy vs. refactored outputs after deterministic normalization.

## Run Locally

### Python (`pytest` + `Hypothesis`)
This repo runs [`test_property_and_differential_starter.py`](test_property_and_differential_starter.py) in CI automatically:

```bash
uv run pytest -v examples/testing/test_property_and_differential_starter.py
```

### TypeScript (`Vitest` + `fast-check`)
Copy [`property_and_differential_starter.test.ts`](property_and_differential_starter.test.ts) into a TypeScript repo and run:

```bash
npm i -D vitest fast-check
npx vitest run property_and_differential_starter.test.ts
```
