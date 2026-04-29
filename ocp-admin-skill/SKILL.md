---
name: ocp-admin-skill
description: OpenShift cluster management tool. Use this to scale deployments, manage pods, and retrieve namespace secrets.
---

# OpenShift Cluster Manager

This skill helps you manage OpenShift resources efficiently using a wrapper script.

## Capabilities

You can use the python script at `scripts/manage_cluster.py` to perform operations.
The script provides the following functions:
- `scale_deployment(namespace, deployment, replicas)`
- `get_secrets(namespace)`

When a user asks you to scale a deployment or get secrets, write a small python script that imports this module and calls the requested function, then execute it.