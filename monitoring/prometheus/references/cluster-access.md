# Cluster Access Reference

How to discover, authenticate to, and connect to Prometheus on Kubernetes and OpenShift clusters.

## Table of Contents

1. [OpenShift Clusters](#openshift-clusters)
2. [Kubernetes Clusters](#kubernetes-clusters)
3. [Authentication Patterns](#authentication-patterns)
4. [Troubleshooting](#troubleshooting)

---

## OpenShift Clusters

OpenShift ships a managed monitoring stack with Prometheus behind a Thanos Querier front-end.

### Discover the Thanos Querier Route

```bash
# List monitoring routes
oc get route -n openshift-monitoring

# Extract the Thanos Querier host
HOST=$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.status.ingress[].host}')
PROM_URL="https://$HOST"
```

### Get Bearer Token

**Current user token (simplest):**
```bash
TOKEN=$(oc whoami -t 2>/dev/null)
```

If this returns empty, the kubeconfig uses client certificate auth instead of a session token. Create a service account token:

**Service account token (for client cert kubeconfigs or automation):**
```bash
oc -n openshift-monitoring create sa prometheus-reader 2>/dev/null
oc adm policy add-cluster-role-to-user cluster-monitoring-view -z prometheus-reader -n openshift-monitoring 2>/dev/null

# OCP 4.11+ / Kubernetes 1.24+ (TokenRequest API)
TOKEN=$(oc create token prometheus-reader -n openshift-monitoring --duration=1h)
```

### Create HTTP Config

```bash
HTTP_CONFIG=$(mktemp /tmp/promtool-http-XXXXXX.yaml)
cat > "$HTTP_CONFIG" <<EOF
authorization:
  type: Bearer
  credentials: $TOKEN
tls_config:
  insecure_skip_verify: true
EOF
```

### Verify Connection

```bash
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up' | head -5
```

### Required RBAC

The requesting account needs the `cluster-monitoring-view` cluster role. Current user (`oc whoami -t`) typically has this if they have cluster-reader or admin access.

### Internal (in-cluster) Access

From within a pod, Thanos Querier is at:
```
https://thanos-querier.openshift-monitoring.svc:9091
```

---

## Kubernetes Clusters

Prometheus on vanilla Kubernetes is typically installed via kube-prometheus-stack (Helm) or the Prometheus Operator.

### Discover Prometheus

```bash
# Search for Prometheus services across all namespaces
kubectl get svc -A | grep -iE 'prometheus|thanos'

# Common namespaces
kubectl get svc -n monitoring
kubectl get svc -n prometheus
kubectl get svc -n kube-prometheus-stack
kubectl get svc -n observability

# Check for Prometheus CRDs (operator-based installs)
kubectl get prometheus -A 2>/dev/null
```

Common service names (varies by Helm release):

| Component | Typical Service Name | Port |
|---|---|---|
| Prometheus | `prometheus-kube-prometheus-prometheus` | 9090 |
| Alertmanager | `prometheus-kube-prometheus-alertmanager` | 9093 |
| Thanos Sidecar | `prometheus-kube-prometheus-thanos-discovery` | 10901 |

### Port-Forward

```bash
# Port-forward to the Prometheus service
PROM_NS="monitoring"  # adjust to actual namespace
PROM_SVC="prometheus-kube-prometheus-prometheus"  # adjust to actual service name

kubectl port-forward -n "$PROM_NS" "svc/$PROM_SVC" 9090:9090 &
PF_PID=$!
sleep 2  # wait for port-forward to establish

PROM_URL="http://localhost:9090"
```

If the service name isn't obvious, find the pod by label:
```bash
kubectl port-forward -n "$PROM_NS" \
  $(kubectl get pods -n "$PROM_NS" -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}') \
  9090:9090 &
PF_PID=$!
```

### HTTP Config for Port-Forward

Port-forwarded connections usually don't require auth:
```bash
HTTP_CONFIG=$(mktemp /tmp/promtool-http-XXXXXX.yaml)
cat > "$HTTP_CONFIG" <<EOF
tls_config:
  insecure_skip_verify: true
EOF
```

If auth is required, extract the token from kubeconfig:
```bash
TOKEN=$(kubectl config view --minify --raw -o jsonpath='{.users[0].user.token}')
cat > "$HTTP_CONFIG" <<EOF
authorization:
  type: Bearer
  credentials: $TOKEN
tls_config:
  insecure_skip_verify: true
EOF
```

### Verify and Clean Up

```bash
# Verify
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up' | head -5

# When done
rm -f "$HTTP_CONFIG"
kill $PF_PID 2>/dev/null
```

---

## Authentication Patterns

### HTTP Config File Schema

The `--http.config.file` YAML supports:

```yaml
# Bearer token (most common for K8s/OCP)
authorization:
  type: Bearer
  credentials: <token-string>
  # OR read from file:
  credentials_file: /path/to/token

# Basic auth
basic_auth:
  username: <string>
  password: <string>

# TLS client certificates (mTLS)
tls_config:
  ca_file: /path/to/ca.crt
  cert_file: /path/to/client.crt
  key_file: /path/to/client.key
  insecure_skip_verify: false
```

### Token Extraction from Kubeconfig

```bash
# Direct token in kubeconfig
kubectl config view --minify --raw -o jsonpath='{.users[0].user.token}'

# OpenShift
oc whoami -t

# Create a short-lived token (K8s 1.24+)
kubectl create token <service-account> -n <namespace> --duration=1h
```

---

## Troubleshooting

### "connection refused" on port-forward
The port-forward process may have died. Check `jobs` and restart it.

### "401 Unauthorized" on OpenShift route
Token may have expired. Refresh with `oc whoami -t` (requires `oc login` session) or create a new SA token.

### "certificate signed by unknown authority"
Add `insecure_skip_verify: true` to the TLS config, or provide the CA cert via `ca_file`.

### "could not find Prometheus service"
Try broader searches:
```bash
kubectl get svc -A | grep -iE '9090|prom|thanos|monitor'
kubectl get pods -A | grep -iE 'prom|thanos'
```
