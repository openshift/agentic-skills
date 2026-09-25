# Argo CD Best Practices Checklist

Assess the repository against each applicable category. Skip categories with zero matching resources.

---

## Sync Policy

- [ ] Automated sync enabled (`spec.syncPolicy.automated`) for environments where auto-deploy is desired
- [ ] `selfHeal: true` set on automated sync to correct drift from manual cluster changes
- [ ] `prune: true` set on automated sync to remove resources deleted from Git
- [ ] `CreateNamespace=true` sync option for apps deploying to dedicated namespaces (`spec.syncPolicy.syncOptions`)
- [ ] `PrunePropagationPolicy=foreground` sync option for clean deletion ordering of dependent resources
- [ ] `ServerSideApply=true` sync option for large manifests (>256KB) or conflict resolution with other controllers
- [ ] Retry configured on `spec.syncPolicy.retry` with reasonable values:
  - `limit`: 2-5 retries
  - `backoff.duration`: 5s-30s initial
  - `backoff.factor`: 2
  - `backoff.maxDuration`: 3m-5m
- [ ] `RespectIgnoreDifferences=true` sync option when using `ignoreDifferences` with automated sync
- [ ] `ApplyOutOfSyncOnly=true` for large applications to reduce sync time

## Application Configuration

- [ ] Explicit `spec.project` reference (not `default` for production apps)
- [ ] `spec.source.targetRevision` pinned to a specific tag, SHA, or release branch (not `HEAD`) for production
- [ ] `spec.destination.server` uses in-cluster reference (`https://kubernetes.default.svc`) or cluster name — not raw URLs that may change
- [ ] `spec.ignoreDifferences` configured for fields managed by external controllers:
  - HPA-managed `spec.replicas` on Deployments
  - Mutating webhook-injected fields (sidecar containers, labels)
  - `metadata.annotations` managed by other operators
  - `status` subresource fields
- [ ] Finalizers set for cascade deletion when Applications should clean up resources on delete:
  - `resources-finalizer.argocd.argoproj.io` for foreground deletion
  - `resources-finalizer.argocd.argoproj.io/background` for background deletion
- [ ] `spec.info` populated with useful metadata (team, slack channel, docs URL)
- [ ] Labels applied consistently for filtering in UI and CLI (`app.kubernetes.io/part-of`, `team`, `env`)

## ApplicationSet Configuration

- [ ] Progressive syncs enabled via `spec.strategy.type: RollingSync` for fleet deployments
  - `maxUpdate` configured (percentage or absolute number)
  - Steps defined for staged rollout (e.g., canary cluster first)
- [ ] `spec.preserveResourcesOnDeletion: true` for safety — prevents accidental mass deletion when generator input changes
- [ ] `spec.template` validated — all `{{placeholder}}` or `{{.values}}` resolve correctly
- [ ] `spec.goTemplate: true` preferred over default fasttemplate for complex templating (conditionals, loops, functions)
- [ ] `spec.templatePatch` used for per-environment overrides instead of duplicating full templates
- [ ] Generators tested independently before combining with `matrix` or `merge`:
  - `list` generator entries validated
  - `git` generator paths/files verified to exist
  - `cluster` generator selector labels confirmed
  - `matrix` combinations produce expected count
- [ ] `spec.ignoreApplicationDifferences` configured when Applications have controller-managed fields
- [ ] `requeueAfterSeconds` set appropriately for generators that poll (SCM provider, pull request)

## Resource Management

- [ ] Resource tracking method appropriate for scale:
  - Annotation-based (default) for most deployments
  - Label-based (`resource.tracking.method: label`) for large-scale (1000+ resources) for better performance
- [ ] Sync waves (`argocd.argoproj.io/sync-wave`) used for ordering:
  - Wave -2 to -1: CRDs, Namespaces
  - Wave 0: Core resources (default)
  - Wave 1+: Resources depending on earlier waves (Ingress after Service, etc.)
- [ ] PreSync hooks for pre-deployment tasks:
  - Database migrations
  - Configuration validation
  - Dependency health checks
- [ ] PostSync hooks for post-deployment tasks:
  - Smoke tests
  - Notification dispatch
  - Cache warming
- [ ] Hook deletion policy configured (`argocd.argoproj.io/hook-delete-policy`):
  - `HookSucceeded` — clean up successful hooks
  - `BeforeHookCreation` — delete previous hook before creating new one
- [ ] Custom health checks defined in `argocd-cm` ConfigMap for CRDs:
  - Argo Rollouts resources
  - Cert-manager Certificates
  - Sealed Secrets
  - Any custom operator CRDs

## Rollout Best Practices

*Applicable only when Argo Rollouts resources (kind: Rollout) are present.*

- [ ] `spec.strategy` explicitly set (canary or blueGreen — not recreate/rollingUpdate which should use Deployment)
- [ ] AnalysisTemplate referenced with meaningful success/failure conditions:
  - Prometheus queries with appropriate thresholds
  - `successCondition` and `failureCondition` both specified
  - `failureLimit` and `count`/`interval` configured
- [ ] Canary strategy:
  - Steps include both `setWeight` and `pause` for controlled progression
  - Pause durations appropriate for environment (shorter in staging, longer in production)
  - `maxSurge` and `maxUnavailable` configured
  - Traffic management configured via Istio/Nginx/ALB (not just replica scaling)
- [ ] Blue-Green strategy:
  - `autoPromotionEnabled: false` for production (manual gate)
  - `prePromotionAnalysis` configured
  - `scaleDownDelaySeconds` set for rollback safety window
  - `activeService` and `previewService` specified
- [ ] Anti-affinity configured between canary/stable pods for realistic testing
- [ ] Rollback:
  - `spec.revisionHistoryLimit` set (default 10 is fine)
  - Manual rollback procedure documented

## Workflow Best Practices

*Applicable only when Argo Workflows resources (kind: Workflow, WorkflowTemplate, CronWorkflow) are present.*

- [ ] `spec.activeDeadlineSeconds` set to prevent runaway workflows consuming resources
- [ ] `spec.retryStrategy` configured with backoff:
  - `limit`: reasonable retry count (2-5)
  - `retryPolicy`: `Always` or `OnError` or `OnTransientError`
  - `backoff.duration`: initial delay
  - `backoff.factor`: multiplier
  - `backoff.maxDuration`: upper bound
- [ ] `spec.podGC.strategy` configured to clean up completed pods:
  - `OnPodCompletion` or `OnPodSuccess` for automatic cleanup
  - `OnWorkflowCompletion` if pod logs need to persist until workflow ends
- [ ] `spec.ttlStrategy` set for automatic workflow cleanup:
  - `secondsAfterCompletion`
  - `secondsAfterSuccess`
  - `secondsAfterFailure`
- [ ] `spec.serviceAccountName` explicitly set (not relying on `default` SA)
- [ ] Resource requests and limits set on workflow step containers:
  - `resources.requests.memory` and `resources.requests.cpu`
  - `resources.limits.memory` to prevent OOM
- [ ] `spec.volumes` and `spec.volumeClaimTemplates` sized appropriately
- [ ] CronWorkflow:
  - `spec.concurrencyPolicy` set (`Allow`, `Forbid`, or `Replace`)
  - `spec.startingDeadlineSeconds` configured
  - `spec.successfulJobsHistoryLimit` and `spec.failedJobsHistoryLimit` set
- [ ] Workflow archived to PostgreSQL/MySQL for historical queries (not just Kubernetes)
