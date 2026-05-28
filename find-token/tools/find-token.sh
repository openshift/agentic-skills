#!/bin/bash
# Generates a complex analysis response with embedded verification tokens.
# Mirrors the operator's AnalysisOutputSchema + components structure.
EVAL_OUTPUT="${EVAL_OUTPUT_DIR:-/app/eval-output}"
DIAG_TOKEN=$(head -c 12 /dev/urandom | base64 | tr -d '=/+')
VERIFY_TOKEN=$(head -c 12 /dev/urandom | base64 | tr -d '=/+')
TIMESTAMP=$(date +%s)

cat > "${EVAL_OUTPUT}/.hidden_token" <<EOF
DIAG_${DIAG_TOKEN}
VERIFY_${VERIFY_TOKEN}
EOF

cat <<EOF
{
  "options": [
    {
      "title": "Token retrieval analysis",
      "summary": "Successfully retrieved verification tokens",
      "diagnosis": {
        "summary": "Token generation system is operational",
        "confidence": "high",
        "rootCause": "Verification requested by eval harness",
        "token": "DIAG_${DIAG_TOKEN}"
      },
      "proposal": {
        "description": "Return the generated tokens for verification",
        "actions": [
          {"type": "verify", "description": "Generate cryptographic tokens"},
          {"type": "report", "description": "Return tokens in structured format"}
        ],
        "risk": "low",
        "reversible": true,
        "estimatedImpact": "none"
      },
      "verification": {
        "description": "Token integrity check",
        "token": "VERIFY_${VERIFY_TOKEN}",
        "steps": [
          {"name": "token-exists", "command": "cat .hidden_token", "expected": "non-empty", "type": "file-check"}
        ],
        "rollbackPlan": {
          "description": "Remove generated tokens",
          "command": "rm -f .hidden_token"
        }
      },
      "rbac": {
        "namespaceScoped": [
          {
            "namespace": "eval-ns",
            "apiGroups": [""],
            "resources": ["secrets"],
            "verbs": ["get"],
            "justification": "Read verification token"
          }
        ],
        "clusterScoped": []
      },
      "components": [
        {
          "type": "token_verification",
          "source": {
            "generator": "find-token.sh",
            "timestamp": "${TIMESTAMP}",
            "entropy_bits": 96
          },
          "tokens": {
            "primary": {
              "value": "DIAG_${DIAG_TOKEN}",
              "algorithm": "base64-urandom",
              "valid": true
            },
            "secondary": {
              "value": "VERIFY_${VERIFY_TOKEN}",
              "algorithm": "base64-urandom",
              "valid": true
            }
          },
          "audit": {
            "outcome": "pass",
            "checks_performed": ["generation", "file_write", "integrity"],
            "findings": [
              {"check": "generation", "result": "pass", "severity": "info", "detail": "Tokens generated with sufficient entropy"},
              {"check": "file_write", "result": "pass", "severity": "info", "detail": "Token file written to disk"},
              {"check": "integrity", "result": "pass", "severity": "info", "detail": "Token values match across all output locations"}
            ]
          }
        }
      ]
    }
  ]
}
EOF
