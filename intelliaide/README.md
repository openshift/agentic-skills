# IntelliAide RCA Skills

IntelliAide is a deep troubleshooting and root-cause analysis pipeline for
OpenShift clusters. It performs a 3-pass analysis (High → Medium → Low
priority) over a must-gather archive and produces a structured diagnosis with
prioritised findings and remediation recommendations.

## How it works

1. **extract_cluster** — validates and unpacks the must-gather archive
   mounted into the sandbox pod from a PVC.
2. **select_files** — uses ML classification and LLM-guided file selection to
   identify the most relevant logs, events, and resource manifests.
3. **analyze_data** — chunks the selected files within the LLM context budget
   and prepares structured analysis prompts.
4. **perform_rca** — the orchestrating Claude session synthesises findings
   across all priority passes and maps results into the standard
   `diagnosis`/`proposal` fields for console rendering.

## Dependencies

Python dependencies are pre-installed in `vendor/` (Python 3.12, x86-64) so
that no `pip install` is required at image build time or at runtime inside the
restricted sandbox environment.

To regenerate `vendor/` for a new Python version, run:

```bash
mkdir -p intelliaide/vendor/
podman run --rm --user root \
  -v $(pwd)/intelliaide:/intelliaide:Z \
  registry.redhat.io/rhel9/python-312:latest \
  pip3.12 install --no-cache-dir --target /intelliaide/vendor/ \
    -r /intelliaide/requirements.txt
```

## Triggering

This skill is invoked automatically when the Proposal request contains
keywords such as `root cause analysis`, `RCA`, `deep analysis`, `deep
troubleshooting`, `must-gather`, or `IntelliAide`.

See [`../examples/setup/09-intelliaide-proposals.yaml`][proposals] for ready-to-use
Proposal templates.
