# product-lifecycle eval

Tests that the agent can use the product-lifecycle skill to query Red Hat
Product Life Cycle data for support status, EOL dates, and OCP version
compatibility — including the `--olmv0`/`--olmv1` split and `--compatibleonly`
upgrade path resolution.

## Prerequisites

### Cluster

A live OpenShift cluster is **not** required. Tests use mock data files
(`testdata/mock_products.json` and `testdata/mock_packagemanifests.json`)
injected into the container by `run.sh`. Internet access is not required.

### Mock data

Mock data was captured from the live [Red Hat Product Life Cycle API](https://access.redhat.com/product-life-cycles/api/v2/products)
on 2026-11-05 and trimmed to relevant products/versions. The packagemanifests
file is hand-crafted to match the `oc get packagemanifests -A -o json` format.

**Products in mock data:**

| Product | Package | Versions |
|---|---|---|
| logging for Red Hat OpenShift | `cluster-logging` | 6.6, 6.5, 6.3, 5.9 |
| compliance operator | `compliance-operator` | 1.10, 1.9 |
| Red Hat OpenShift Container Platform | (none) | 4.21, 4.14 |
| Red Hat OpenShift Pipelines | `openshift-pipelines-operator-rh` | 1.22, 1.18, 1.16 |
| web terminal operator | `web-terminal` | 1.16, 1.13, 1.12 |
| Red Hat OpenShift GitOps | `openshift-gitops-operator` | 1.22, 1.21 |
| Red Hat Advanced Cluster Security for Kubernetes | `rhacs-operator` | 5.0, 4.10 |
| cert-manager operator for Red Hat OpenShift | `openshift-cert-manager-operator` | 1.20, 1.19 |
| Red Hat OpenShift Serverless | `serverless-operator` | 1.37, 1.36 |

**Not in mock data (for "not found" tests):** `grafana-operator`, `istio-workspace-operator`

### Operators used in tests

Based on a real OCP cluster setup:

**OLMv0 (Subscription-managed):**

| Operator | Package | Version | Channel |
|---|---|---|---|
| Red Hat OpenShift GitOps | `openshift-gitops-operator` | 1.21.6 | gitops-1.21 |
| Red Hat ACS | `rhacs-operator` | 4.10.11 | rhacs-4.10 |
| cert-manager | `openshift-cert-manager-operator` | 1.20.0 | stable-v1 |
| Grafana (community) | `grafana-operator` | 5.21.2 | v5 |

**OLMv1 (ClusterExtension-managed):**

| Operator | Package | Version |
|---|---|---|
| Red Hat OpenShift Pipelines | `openshift-pipelines-operator-rh` | 1.22.0 |
| Red Hat OpenShift Serverless | `serverless-operator` | 1.36.1 |
| istio-workspace | `istio-workspace-operator` | 0.5.2 |

## Test cases

| Test | What it exercises |
|---|---|
| `plc_olmv0_batch_check` | `--olmv0` batch with found + not-found operators |
| `plc_olmv1_batch_check` | `--olmv1` batch with incompatible operator |
| `plc_mixed_v0_v1_check` | Mixed `--olmv0` + `--olmv1` in one call |
| `plc_compatibleonly_upgrade_path` | `--compatibleonly` with `source_catalogs` upgrade path (cluster-logging v5.9.14) |
| `plc_olmv0_upgrade_multi_channel` | OLMv0 EOL operator upgrade with multiple channels (cluster-logging v6.3.0) |
| `plc_olmv1_upgrade_path` | OLMv1 upgrade path — lifecycle-only, no catalog data (serverless v1.36.1) |
| `plc_ocp_platform_status` | `products` command for platform lifecycle |
| `plc_product_ocp_compat` | `products --ocp` for operator compatibility |
| `plc_unknown_operator` | Unknown operator (no PLC data) |

## Running

```bash
bash evals/run.sh -k "product-lifecycle"
```
