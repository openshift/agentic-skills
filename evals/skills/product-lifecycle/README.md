# product-lifecycle eval

Tests that the agent can query the [Red Hat Product Life Cycle API](https://access.redhat.com/product-life-cycles/api/v2/products) for product support status, EOL dates, and OCP version compatibility using the product-lifecycle skill.

## Prerequisites

### Cluster

A live OpenShift cluster is not required to run these evals. The test cases embed operator metadata in the query, and the agent queries the public [Red Hat Product Life Cycle API](https://access.redhat.com/product-life-cycles/api/v2/products) directly. Internet access is required.

The operator metadata in each test case was collected from a real OCP 4.21.5 cluster on GCP (6 nodes: 3 master + 3 worker) with these OLM operators installed:

| Operator | Package | Version | Channel |
|---|---|---|---|
| Red Hat OpenShift Logging | `cluster-logging` | 6.3.1 | stable-6.3 |
| Compliance Operator | `compliance-operator` | 1.9.0 | stable |
| Red Hat OpenShift Pipelines | `openshift-pipelines-operator-rh` | 1.22.0 | latest |
| Web Terminal | `web-terminal` | 1.16.0 | fast |
| DevWorkspace Operator | `devworkspace-operator` | 0.41.0 | fast |

> **Note:** Some operator versions were adjusted from the real cluster values to better exercise test conditions (e.g. `cluster-logging` uses 6.3.1 instead of 6.5.1 to simulate OCP 4.21 incompatibility).

## Ground truth

Expected values come from the live PLC API. Verify using `plc_lookup.py` — the same CLI the agent uses (see [SKILL.md](../../../cluster-update/product-lifecycle/SKILL.md)):

```bash
# OCP 4.21 — should show "Full Support"
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform" \
  | jq '.results[] | select(.version == "4.21") | {version, status}'

# OCP 4.14 — should show "Extended Support"
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform" \
  | jq '.results[] | select(.version == "4.14") | {version, status}'

# cluster-logging — check compatibility with OCP 4.21
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21

# compliance-operator v1.9 — should show "Full Support"
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "compliance operator"

# Batch check — all 5 operators against OCP 4.21 using olm-check
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 \
  --operators '[{"package":"cluster-logging","version":"6.3.1"},{"package":"compliance-operator","version":"1.9.0"},{"package":"openshift-pipelines-operator-rh","version":"1.22.0"},{"package":"web-terminal","version":"1.16.0"},{"package":"devworkspace-operator","version":"0.41.0"}]'
```

## Running

```bash
bash evals/run.sh -k "product-lifecycle"
```
