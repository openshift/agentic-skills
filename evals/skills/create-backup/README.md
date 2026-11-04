# Create backup checks

Run the script behavior tests without a cluster:

```bash
bash evals/skills/create-backup/test-scripts.sh
```

The test uses a temporary `oc` and OADP CLI stub. It covers preflight, CLI preview and submission, permission fallback, duplicate names, monitoring, and incomplete volume inspection.
The repository unit job discovers `tests/test_create_backup_scripts.py` and runs this suite when `jq` is available in its image.

The cases in `test_cases.yaml` exercise agent selection and interpretation through the repository eval harness. Run them when the `lightspeed-agentic-sandbox` image, Python dependencies, and a model provider are available:

```bash
bash evals/run.sh -k "create-backup"
```
