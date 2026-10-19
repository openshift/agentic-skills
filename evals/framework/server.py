"""Eval-only HTTP adapter for the batch sandbox image."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lightspeed_agentic.config import (
    parse_agent_timeout,
    parse_max_turns,
    resolve_router_model,
    resolve_sdk,
)
from lightspeed_agentic.factory import create_provider
from lightspeed_agentic.run_agent import run_agent_query
from lightspeed_agentic.tls import configure_tls


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    configure_tls()
    sdk = resolve_sdk()
    model = resolve_router_model(sdk.name)
    timeout_seconds = parse_agent_timeout()
    max_turns = parse_max_turns()
    skills_dir = os.environ.get("LIGHTSPEED_SKILLS_DIR", "/app/skills")

    async def run_query(
        body: dict[str, Any], request_timeout: int
    ) -> dict[str, Any]:
        provider = create_provider(sdk.name)
        try:
            result = await run_agent_query(
                provider,
                prompt=body["query"],
                system_prompt=body.get(
                    "systemPrompt", "You are a helpful assistant."
                ),
                output_schema=body.get("outputSchema"),
                context=None,
                skills_dir=skills_dir,
                model=model,
                max_turns=max_turns,
                timeout_seconds=request_timeout,
            )
            return result.output
        finally:
            await provider.aclose()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            if self.path != "/v1/agent/run":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Request must be a JSON object")
                if not isinstance(body.get("query"), str):
                    raise ValueError("query must be a string")
                if not isinstance(
                    body.get("systemPrompt", "You are a helpful assistant."),
                    str,
                ):
                    raise ValueError("systemPrompt must be a string")
                schema = body.get("outputSchema")
                if schema is not None and not isinstance(schema, dict):
                    raise ValueError("outputSchema must be an object")
                timeout_ms = body.get("timeout_ms", timeout_seconds * 1000)
                if type(timeout_ms) is not int or timeout_ms <= 0:
                    raise ValueError("timeout_ms must be a positive integer")
                request_timeout = min(
                    timeout_seconds, (timeout_ms + 999) // 1000
                )
            except (KeyError, TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return

            try:
                output = asyncio.run(run_query(body, request_timeout))
            except Exception:
                logging.exception("Eval request failed")
                self._send_json(
                    500, {"error": "Eval request failed; see container logs"}
                )
                return

            self._send_json(200, output)

    with ThreadingHTTPServer(("0.0.0.0", 8080), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
