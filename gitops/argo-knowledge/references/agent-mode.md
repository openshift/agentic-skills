# Argo CD Agent Mode

Reference for the argocd-agent project — a hub-and-spoke architecture for managing
multiple clusters where the agent initiates connections to the control plane, eliminating
the need for the control plane to have direct API access to workload clusters.

**Project:** [argoproj-labs/argocd-agent](https://github.com/argoproj-labs/argocd-agent)
**Docs:** [argocd-agent.readthedocs.io](https://argocd-agent.readthedocs.io/latest/)
**Status:** GA in Red Hat OpenShift GitOps 1.19; upstream still pre-v1

## Architecture

### Components

| Component | Runs On | Role |
|-----------|---------|------|
| Principal | Control plane cluster | Accepts agent connections, serves as config hub and observability aggregation point |
| Agent | Each workload cluster | Initiates gRPC connection to principal, manages local Argo CD reconciliation |
| Local Argo CD | Each workload cluster | application-controller + repo-server + redis running locally for autonomous operation |

### Communication Model

- **Agent-initiated only** — connections always flow from workload clusters to the control plane, never the reverse
- **gRPC bi-directional streaming** — both parties send and receive messages over the same connection
- **mTLS everywhere** — all communications encrypted and certificate-authenticated
- **Lightweight** — synchronizes only Argo CD config objects (Applications, AppProjects, repo config), not cluster resources
- **Resilient** — designed for unreliable connectivity; workload clusters continue reconciling independently when disconnected

### What Gets Synchronized

The agent syncs Argo CD configuration resources between control plane and workload clusters:
- `Application` specs and status
- `AppProject` configurations
- Repository credentials and configuration
- Does NOT sync arbitrary Kubernetes resources — reconciliation happens locally

## Operational Modes

### Managed Mode

- Application specs originate on the **control plane** and are distributed to workload clusters
- Control plane is the source of truth for what should be deployed
- Equivalent to traditional Argo CD but without requiring cluster credentials on the control plane
- Best for: centralized platform teams managing fleet deployments

### Autonomous Mode

- Application specs are defined **locally on workload clusters**
- Changes sync back to the control plane for observability only
- Workload clusters operate independently even during connectivity loss
- Best for: edge deployments, air-gapped environments, teams needing local autonomy

### Mixed Mode

- Different clusters can operate in different modes within the same fleet
- Example: production clusters in managed mode, edge clusters in autonomous mode

## Fully Autonomous Pattern (Recommended)

The recommended production deployment runs a complete Argo CD stack on each workload cluster:

- **application-controller** — local reconciliation, no dependency on control plane
- **repo-server** — local manifest generation from Git/OCI/Helm sources
- **redis** — local caching

The control plane serves as a configuration hub and observability aggregation point.
Workload clusters continue all GitOps operations during control plane maintenance,
upgrades, or outages.

## When to Use Agent Mode

| Scenario | Traditional Argo CD | Agent Mode |
|----------|-------------------|------------|
| Small fleet (< 10 clusters) | Works well | Overkill |
| Large fleet (50+ clusters) | Resource strain on control plane | Designed for this |
| Air-gapped / restricted networks | Requires VPN or firewall rules | Agent initiates outbound only |
| Edge / IoT / remote sites | Impractical — unreliable connectivity | Built for intermittent connectivity |
| Multi-cloud | Each cloud needs inbound rules | Outbound-only from each cloud |
| Compliance requires no stored credentials | Must store cluster creds centrally | No cluster credentials on control plane |

## Comparison with Traditional Multi-Cluster

| Aspect | Traditional | Agent Mode |
|--------|------------|------------|
| Credential storage | Control plane stores kubeconfig/tokens for every cluster | No cluster credentials on control plane |
| Network direction | Control plane → cluster API (inbound to cluster) | Agent → control plane (outbound from cluster) |
| Failure mode | Control plane down = no sync for any cluster | Each cluster continues independently |
| Resource scaling | Linear with cluster count on control plane | Compute distributed to workload clusters |
| Security surface | Concentrated — control plane has access to all clusters | Distributed — each agent has minimal permissions |
