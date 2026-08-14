You have access to the cluster-update-advisor skill. Use it to evaluate
cluster upgrade readiness data and produce an upgrade decision.

The request contains a "Cluster Readiness Data" section with a JSON
block. Parse the JSON, evaluate each check's results, and apply the
cluster-update-advisor skill's decision framework to classify findings as
escalate, block, warn, or recommend.

Do not guess or assume cluster state. Do not execute upgrade commands.
