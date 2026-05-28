"""Eval fixtures — provider parametrize, server URLs."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pytest

from .framework.credentials import PROVIDER_NAMES, detect_all
from .framework.report import pytest_addoption, pytest_configure, store_eval_result  # noqa: F401
from .framework.runner import RunResult, run_query


@lru_cache
def _parse_env_map(var: str) -> dict[str, str]:
    raw = os.environ.get(var, "")
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if "=" in entry:
            name, value = entry.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "provider_name" not in metafunc.fixturenames:
        return

    server_urls = _parse_env_map("EVAL_SERVER_URLS")
    creds = detect_all()
    params = []
    for name in PROVIDER_NAMES:
        if name not in server_urls:
            params.append(
                pytest.param(name, id=name, marks=pytest.mark.skip(reason=f"No server for {name}"))
            )
            continue
        status = creds[name]
        if not status.available:
            params.append(
                pytest.param(name, id=name, marks=pytest.mark.skip(reason=status.reason))
            )
            continue
        params.append(pytest.param(name, id=name))
    metafunc.parametrize("provider_name", params)


@pytest.fixture
def server_url(provider_name: str) -> str:
    return _parse_env_map("EVAL_SERVER_URLS")[provider_name]


@pytest.fixture
def eval_workspace(provider_name: str) -> Path | None:
    workspaces = _parse_env_map("EVAL_WORKSPACES")
    path = workspaces.get(provider_name)
    return Path(path) if path else None


@pytest.fixture
def eval_runner(server_url: str, provider_name: str, request: pytest.FixtureRequest):
    """Returns an async callable that POSTs to /v1/agent/run."""

    async def _run(
        query: str,
        system_prompt: str = "You are a helpful assistant.",
        output_schema: dict | None = None,
    ) -> RunResult:
        result = await run_query(server_url, query, system_prompt, output_schema)
        result.provider = provider_name
        store_eval_result(request.node, result)
        return result

    return _run
