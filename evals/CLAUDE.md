# Evals

## Quick Reference

```bash
# Run all evals (Claude opus-4-6, 4 parallel workers)
EVAL_PROVIDERS=claude ANTHROPIC_MODEL=claude-opus-4-6 PYTEST="python3 -m pytest -n 4" bash evals/run.sh -k "claude and not deepagents" -v

# Run one skill's evals
bash evals/run.sh -k "find-token"
bash evals/run.sh -k "openshift-docs"

# Run a single test case
bash evals/run.sh -k "find_token_tool_execution"

# Generate JSON report
bash evals/run.sh --eval-report=evals/report.json
```

## Before Running

- Container image must exist: `podman images lightspeed-agentic-sandbox` — if missing, build from [lightspeed-agentic-sandbox](https://github.com/openshift/lightspeed-agentic-sandbox) with `podman build -t lightspeed-agentic-sandbox:latest .`
- Clean up stale containers before re-running: `podman stop -a; podman rm -fa`

## After Running

- Always clean up: `podman stop -a; podman rm -fa; rm -rf .eval-workspaces`
- Check results with: `grep -E "PASSED|FAILED|passed|failed" <output>`

## Adding a New Skill Eval

See `evals/skills/find-token/` as the reference — it demonstrates both verification patterns:

1. **Static matching** (`find_token_static_fields`): `expected` with field: value pairs for deterministic outputs
2. **Custom verification** (`find_token_tool_execution`): `expected: { _fn: verify_tokens }` with a `verify.py` function for runtime data (tool-generated tokens, live cluster queries)

Each skill eval directory needs:
- `system_prompt.md` — the system prompt for the agent
- `test_cases.yaml` — test cases with query, schema, and expected
- `verify.py` (optional) — custom verification functions referenced by `_fn`

Use enums, booleans, and integers in schemas — never free-form text.

## Debugging Failures

When a test fails, the assertion shows the expected vs actual value. To investigate:
1. Verify the expected value is correct by checking the skill's source data
2. If the expected value is wrong, fix it in `test_cases.yaml`
3. If the agent returned wrong data, check if the query is ambiguous or if the schema description needs a stronger skill hint
