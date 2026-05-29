# product-lifecycle eval

Tests that the agent can use `plc_lookup.py` to query the Red Hat Product Life Cycle API for product support status, EOL dates, and OCP version compatibility.

## Prerequisites

### Cluster

A live OpenShift cluster is required. The test cases embed operator metadata in the query (so the lightspeed operator does not need to be installed), but the agent still probes the cluster for deeper investigation and calls `plc_lookup.py` which queries the live [Red Hat Product Life Cycle API](https://access.redhat.com/support/policy/update_policies).

The following OLM operators must be installed on the cluster:

| Operator | Package | Version | Channel |
|---|---|---|---|
| Red Hat OpenShift Logging | `cluster-logging` | 6.5.1 | stable-6.5 |
| Compliance Operator | `compliance-operator` | 1.9.0 | stable |
| Red Hat OpenShift Pipelines | `openshift-pipelines-operator-rh` | 1.22.0 | latest |
| Web Terminal | `web-terminal` | 1.16.0 | fast |
| DevWorkspace Operator | `devworkspace-operator` | 0.41.0 | fast |

Cluster version: OCP 4.21.5 (GCP, 6 nodes: 3 master + 3 worker)

### Install operators (if reproducing on a fresh cluster)

```bash
# cluster-logging
oc create ns openshift-logging
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-logging
  namespace: openshift-logging
spec:
  targetNamespaces: [openshift-logging]
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: cluster-logging
  namespace: openshift-logging
spec:
  channel: stable-6.5
  name: cluster-logging
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# compliance-operator
oc create ns openshift-compliance
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-compliance
  namespace: openshift-compliance
spec:
  targetNamespaces: [openshift-compliance]
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: compliance-operator
  namespace: openshift-compliance
spec:
  channel: stable
  name: compliance-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# openshift-pipelines (cluster-scoped, no OperatorGroup needed)
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-pipelines-operator-rh
  namespace: openshift-operators
spec:
  channel: latest
  name: openshift-pipelines-operator-rh
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# web-terminal (cluster-scoped)
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: web-terminal
  namespace: openshift-operators
spec:
  channel: fast
  name: web-terminal
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

## Ground truth

Expected values come from the live PLC v2 API. Verify with:

```bash
# OCP 4.21 → supported
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform" --ocp 4.21

# OCP 4.14 → extended
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform" --ocp 4.14

# cluster-logging → supported, OCP 4.21 compatible
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21

# compliance-operator → supported (found by product name, not olm-check)
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "compliance operator"

# Batch check — 2 found (cluster-logging, web-terminal), 3 unavailable
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --operators '[
  {"package":"cluster-logging"},
  {"package":"compliance-operator"},
  {"package":"devworkspace-operator"},
  {"package":"openshift-pipelines-operator-rh"},
  {"package":"web-terminal"}
]'
```

## Running

```bash
bash evals/run.sh -k "product-lifecycle"
```
