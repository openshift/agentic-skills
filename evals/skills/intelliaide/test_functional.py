"""Standalone functional tests for IntelliAide pipeline scripts.

These tests exercise IntelliAide's Python scripts directly — without an LLM,
without a sandbox container, and without API keys.  They follow the Lightspeed
operator team's unit-testing pattern: mock inputs, call the code, verify outputs.

Run independently (no container / no API keys required):
    python3 -m pytest evals/skills/intelliaide/test_functional.py -v

Or filter by marker alongside the full eval suite:
    python3 -m pytest evals/ -v -m unit
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ── Path constants ───────────────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _THIS_DIR.parents[2]          # .../agentic-skills/
SKILL_DIR = REPO_ROOT / "intelliaide"


# ── Import extract_cluster.py directly (zero vendor deps) ───────────────────

def _import_skill_script(name: str):
    """Import a top-level IntelliAide script by filename (no package needed)."""
    path = SKILL_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ec = _import_skill_script("extract_cluster")


# ── Vendor-dep availability check (for subprocess-based tests) ───────────────

def _vendor_imports_available() -> bool:
    """Return True if the vendored DataAnalyzer import chain works."""
    env = {**os.environ, "SKILL_DIR": str(SKILL_DIR), "ORCHESTRATOR_QUIET": "1"}
    code = (
        "import os, sys; "
        "sd = os.environ['SKILL_DIR']; "
        "sys.path.insert(0, os.path.join(sd, 'vendor')); "
        "sys.path.insert(0, os.path.join(sd, 'Main-program')); "
        "sys.path.insert(0, sd); "
        "from data_analyzer import DataAnalyzer; print('ok')"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, env=env,
        )
        return r.returncode == 0 and "ok" in r.stdout
    except Exception:
        return False


_HAS_VENDOR = _vendor_imports_available()
_SKIP_VENDOR = pytest.mark.skipif(
    not _HAS_VENDOR,
    reason="Vendored deps (drain3 etc.) not importable with this Python",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_script(script_name: str, args: list[str], timeout: int = 120):
    """Run an IntelliAide script via subprocess and return CompletedProcess."""
    cmd = [sys.executable, str(SKILL_DIR / script_name)] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "ORCHESTRATOR_QUIET": "1"},
    )


def _parse_stdout_json(stdout: str) -> dict[str, Any]:
    """Extract the last JSON object from stdout (scripts emit progress on stderr)."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError(f"No JSON found in stdout:\n{stdout[:500]}")


# ── Mock must-gather data generators ────────────────────────────────────────

_MOCK_ETCD_LOG = "\n".join(
    # 20 repeated high-frequency errors (Drain3 should cluster these)
    [
        f"2026-06-01T10:00:{i:02d}.000000Z E | rafthttp: failed to reach "
        f"the peer https://etcd-1.openshift-etcd.svc:2380 (connection refused)"
        for i in range(20)
    ]
    # 2 rare errors (unique — Drain3 should flag these)
    + [
        "2026-06-01T10:00:25.000000Z E | etcdserver: leader changed from member-a to member-b",
        "2026-06-01T10:00:26.000000Z E | etcdserver: request timed out waiting for node response",
    ]
    # 3 warnings
    + [
        "2026-06-01T10:00:27.000000Z W | etcdserver: read-only range request took too long (2.503s)",
        "2026-06-01T10:00:28.000000Z W | etcdserver: read-only range request took too long (3.124s)",
        "2026-06-01T10:00:29.000000Z W | etcdserver: slow fdatasync took 1.012s",
    ]
    # 3 info lines
    + [
        "2026-06-01T10:00:30.000000Z I | etcdserver: compacted raft log at index 234567",
        "2026-06-01T10:00:31.000000Z I | etcdserver: compacted raft log at index 234568",
        "2026-06-01T10:00:32.000000Z I | mvcc: store.index: compact 123456",
    ]
) + "\n"


_MOCK_CLUSTER_OPERATOR_YAML = """\
apiVersion: config.openshift.io/v1
kind: ClusterOperator
metadata:
  name: etcd
status:
  conditions:
  - type: Degraded
    status: "True"
    reason: EtcdMembersDegraded
    message: "1 of 3 members are available, etcd-1 is not started"
    lastTransitionTime: "2026-06-01T10:00:00Z"
  - type: Available
    status: "False"
    reason: EtcdMembersNotAvailable
    message: "Not enough etcd members are available"
    lastTransitionTime: "2026-06-01T10:00:00Z"
  - type: Progressing
    status: "True"
    reason: EtcdWaitingForMembers
    message: "Waiting for etcd-1 to join"
    lastTransitionTime: "2026-06-01T09:55:00Z"
"""

_MOCK_NODE_YAML = """\
apiVersion: v1
kind: Node
metadata:
  name: worker-0.example.com
status:
  conditions:
  - type: Ready
    status: "True"
    reason: KubeletReady
    message: "kubelet is posting ready status"
  - type: MemoryPressure
    status: "False"
  - type: DiskPressure
    status: "False"
"""


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_must_gather(tmp_path: Path) -> Path:
    """Build a minimal mock must-gather bundle (>=3 files) under tmp_path."""
    mg = tmp_path / "data-input"

    log_dir = mg / "namespaces" / "openshift-etcd" / "pods" / "etcd-0" / "etcd" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "current.log").write_text(_MOCK_ETCD_LOG)

    yaml_dir = mg / "cluster-scoped-resources"
    yaml_dir.mkdir(parents=True)
    (yaml_dir / "clusteroperators.yaml").write_text(_MOCK_CLUSTER_OPERATOR_YAML)
    (yaml_dir / "nodes.yaml").write_text(_MOCK_NODE_YAML)

    return mg


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """Return an empty temporary job directory."""
    d = tmp_path / "job"
    d.mkdir()
    return d


# ═════════════════════════════════════════════════════════════════════════════
# extract_cluster.py  —  validation & unwrap logic (no vendor deps)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestExtractClusterValidation:
    """Unit tests for extract_cluster.py data-source validation."""

    def test_happy_path_succeeds(self, mock_must_gather, monkeypatch):
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", mock_must_gather)
        cluster_dir, success, error = _ec._check_data_source()
        assert success, f"Expected success, got: {error}"
        assert Path(cluster_dir).exists()

    def test_nonexistent_mount_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", tmp_path / "no-such-dir")
        _, success, error = _ec._check_data_source()
        assert not success
        assert "No data source" in error

    def test_empty_dir_fails(self, tmp_path, monkeypatch):
        empty = tmp_path / "data-input"
        empty.mkdir()
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", empty)
        _, success, error = _ec._check_data_source()
        assert not success
        assert "empty" in error.lower()

    def test_too_few_files_fails(self, tmp_path, monkeypatch):
        sparse = tmp_path / "data-input"
        sparse.mkdir()
        (sparse / "only_one.yaml").write_text("key: value")
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", sparse)
        _, success, error = _ec._check_data_source()
        assert not success
        assert "too few" in error.lower()

    def test_exactly_three_files_passes(self, tmp_path, monkeypatch):
        di = tmp_path / "data-input"
        di.mkdir()
        for i in range(3):
            (di / f"file{i}.yaml").write_text(f"k: {i}")
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", di)
        _, success, _ = _ec._check_data_source()
        assert success

    def test_lost_and_found_ignored(self, tmp_path, monkeypatch):
        di = tmp_path / "data-input"
        di.mkdir()
        (di / "lost+found").mkdir()
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", di)
        entries = _ec._real_entries(di)
        assert all(e.name != "lost+found" for e in entries)

    def test_hidden_files_ignored(self, tmp_path, monkeypatch):
        di = tmp_path / "data-input"
        di.mkdir()
        (di / ".hidden").write_text("secret")
        (di / "visible.yaml").write_text("k: v")
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", di)
        entries = _ec._real_entries(di)
        assert all(not e.name.startswith(".") for e in entries)


@pytest.mark.unit
class TestExtractClusterUnwrap:
    """Unit tests for single-child wrapper directory unwrapping."""

    def test_unwraps_through_single_child(self, tmp_path):
        deep = tmp_path / "w1" / "w2" / "data"
        deep.mkdir(parents=True)
        (deep / "f1.yaml").write_text("a: 1")
        (deep / "f2.yaml").write_text("b: 2")
        result = _ec._unwrap_single_child_dirs(tmp_path)
        assert result == deep

    def test_stops_at_max_depth(self, tmp_path):
        current = tmp_path
        for i in range(6):
            current = current / f"level{i}"
        current.mkdir(parents=True)
        (current / "data.yaml").write_text("x: 1")
        result = _ec._unwrap_single_child_dirs(tmp_path)
        assert result.name == f"level{_ec._MAX_UNWRAP_DEPTH - 1}"

    def test_stops_when_fanout(self, tmp_path):
        (tmp_path / "wrapper" / "dir_a").mkdir(parents=True)
        (tmp_path / "wrapper" / "dir_b").mkdir(parents=True)
        (tmp_path / "wrapper" / "dir_a" / "f.yaml").write_text("")
        (tmp_path / "wrapper" / "dir_b" / "f.yaml").write_text("")
        result = _ec._unwrap_single_child_dirs(tmp_path)
        assert result.name == "wrapper"

    def test_flat_dir_returns_self(self, tmp_path):
        (tmp_path / "a.yaml").write_text("")
        (tmp_path / "b.yaml").write_text("")
        result = _ec._unwrap_single_child_dirs(tmp_path)
        assert result == tmp_path


@pytest.mark.unit
class TestExtractClusterMain:
    """Integration tests for extract_cluster.py main() flow."""

    def test_state_json_created_on_success(
        self, mock_must_gather, tmp_path, monkeypatch,
    ):
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", mock_must_gather)
        monkeypatch.setattr(_ec, "_JOB_BASE", str(tmp_path / "jobs"))
        monkeypatch.setattr(sys, "argv", [
            "extract_cluster.py", "--query", "etcd pods not ready",
        ])

        _ec.main()  # exits 0 on success

        job_dirs = list((tmp_path / "jobs").iterdir())
        assert len(job_dirs) == 1
        state = json.loads((job_dirs[0] / "state.json").read_text())
        assert state["query"] == "etcd pods not ready"
        assert state["mode"] == "must-gather"
        assert "cluster_dir" in state

    def test_state_json_created_on_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_ec, "_DATA_INPUT_DIR", tmp_path / "nope")
        monkeypatch.setattr(_ec, "_JOB_BASE", str(tmp_path / "jobs"))
        monkeypatch.setattr(sys, "argv", [
            "extract_cluster.py", "--query", "test",
        ])

        with pytest.raises(SystemExit) as exc:
            _ec.main()
        assert exc.value.code == 1

        job_dirs = list((tmp_path / "jobs").iterdir())
        assert len(job_dirs) == 1
        state = json.loads((job_dirs[0] / "state.json").read_text())
        assert state["query"] == "test"


# ═════════════════════════════════════════════════════════════════════════════
# analyze_data.py  —  ML pipeline / Drain3 log deduplication (needs vendor)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
@_SKIP_VENDOR
class TestAnalyzeData:
    """Functional tests for analyze_data.py — Drain3 log deduplication & ML."""

    def test_log_deduplication(self, mock_must_gather, job_dir):
        """Drain3 should compress 28 log lines into categorized error templates.

        The mentor's requirement: 'to test the Drain3 algorithm/ML we can give
        input as a few long lines which some redundant lines and make sure it is
        able to return the relevant logs.'
        """
        log_path = str(
            mock_must_gather / "namespaces" / "openshift-etcd"
            / "pods" / "etcd-0" / "etcd" / "logs" / "current.log"
        )

        self._write_job_state(job_dir, mock_must_gather)
        self._write_file_selection(
            job_dir, mock_must_gather,
            high=[{"original": log_path, "resolved": log_path,
                   "found": True, "reason": "etcd pod log"}],
        )

        result = _run_script("analyze_data.py", [
            "--job-dir", str(job_dir), "--priority", "high",
        ])
        assert result.returncode == 0, self._fmt_err(result)

        output = _parse_stdout_json(result.stdout)
        assert output["log_files"] >= 1, "Expected at least one log file processed"

        analysis = json.loads(Path(output["analysis_path"]).read_text())
        assert analysis["priority"] == "high"
        assert isinstance(analysis["log_entries"], list)

        if analysis["log_entries"]:
            total_output_lines = sum(
                entry["content"].count("\n") for entry in analysis["log_entries"]
            )
            input_line_count = _MOCK_ETCD_LOG.strip().count("\n") + 1
            assert total_output_lines < input_line_count, (
                f"Drain3 should deduplicate: {total_output_lines} output lines "
                f">= {input_line_count} input lines"
            )

    def test_empty_priority_produces_empty_analysis(self, job_dir, tmp_path):
        """An empty file-selection tier should produce a valid empty analysis."""
        mg = tmp_path / "empty-mg"
        mg.mkdir()
        self._write_job_state(job_dir, mg)
        self._write_file_selection(job_dir, mg, high=[])

        result = _run_script("analyze_data.py", [
            "--job-dir", str(job_dir), "--priority", "high",
        ])
        assert result.returncode == 0, self._fmt_err(result)

        output = _parse_stdout_json(result.stdout)
        assert output["yaml_files"] == 0
        assert output["log_files"] == 0
        assert output["log_entries"] == 0

        analysis = json.loads(Path(output["analysis_path"]).read_text())
        assert analysis["log_entries"] == []
        assert analysis["yaml_errors"] == {}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _write_job_state(job_dir: Path, cluster_dir: Path):
        (job_dir / "state.json").write_text(json.dumps({
            "job_id": "func0001",
            "job_dir": str(job_dir),
            "cluster_dir": str(cluster_dir),
            "query": "etcd pods not ready",
            "mode": "must-gather",
        }))

    @staticmethod
    def _write_file_selection(
        job_dir: Path, cluster_dir: Path,
        high: list | None = None,
        medium: list | None = None,
        low: list | None = None,
    ):
        (job_dir / "file_selection.json").write_text(json.dumps({
            "query": "etcd pods not ready",
            "cluster_dir": str(cluster_dir),
            "problem_category": "etcd",
            "high": high or [],
            "medium": medium or [],
            "low": low or [],
        }))

    @staticmethod
    def _fmt_err(result) -> str:
        return (
            f"analyze_data.py exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout[:2000]}\n"
            f"--- stderr ---\n{result.stderr[:2000]}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# perform_rca.py  —  chunking & reduce phases (needs vendor)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
@_SKIP_VENDOR
class TestPerformRcaChunks:
    """Tests for perform_rca.py --mode chunks (prompt chunking)."""

    def test_creates_manifest_and_chunk_files(self, job_dir):
        """Given log entries, chunks mode should produce chunk prompts + manifest."""
        self._setup_job(job_dir, log_entries=[{
            "file": "current_RareError.txt",
            "content": (
                "E | etcdserver: leader changed from member-a to member-b\n"
                "E | etcdserver: request timed out waiting for node response\n"
            ),
            "original_size": 5000,
        }])

        result = _run_script("perform_rca.py", [
            "--job-dir", str(job_dir), "--priority", "high",
        ])
        assert result.returncode == 0, self._fmt_err(result)

        output = _parse_stdout_json(result.stdout)
        assert output["mode"] == "chunks"
        assert output["chunk_count"] >= 1
        assert output["has_medium"] is True
        assert output["has_low"] is False

        manifest = json.loads(Path(output["manifest_path"]).read_text())
        assert manifest["chunk_count"] == output["chunk_count"]
        for chunk_info in manifest["chunk_files"]:
            chunk_path = Path(chunk_info["path"])
            assert chunk_path.exists(), f"Missing chunk file: {chunk_path}"
            assert chunk_info["estimated_tokens"] > 0

    def test_empty_analysis_gives_zero_chunks(self, job_dir):
        """No data at all should produce chunk_count=0."""
        self._setup_job(job_dir, log_entries=[], yaml_errors={})

        result = _run_script("perform_rca.py", [
            "--job-dir", str(job_dir), "--priority", "high",
        ])
        assert result.returncode == 0
        assert _parse_stdout_json(result.stdout)["chunk_count"] == 0

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _setup_job(
        job_dir: Path,
        log_entries: list | None = None,
        yaml_errors: dict | None = None,
        priority: str = "high",
    ):
        (job_dir / "state.json").write_text(json.dumps({
            "job_id": "func0002",
            "job_dir": str(job_dir),
            "cluster_dir": "/tmp/fake-cluster",
            "query": "etcd pods are not ready after node reboot",
            "mode": "must-gather",
        }))
        (job_dir / f"analysis_{priority}.json").write_text(json.dumps({
            "priority": priority,
            "yaml_errors": yaml_errors if yaml_errors is not None else {},
            "log_entries": log_entries if log_entries is not None else [],
            "yaml_files": 0,
            "log_files": 1 if log_entries else 0,
            "failed_files": [],
        }))
        (job_dir / "file_selection.json").write_text(json.dumps({
            "query": "etcd pods are not ready",
            "cluster_dir": "/tmp/fake-cluster",
            "high": [{"original": "etcd.log", "resolved": "etcd.log",
                       "found": True, "reason": "test"}],
            "medium": [{"original": "api.log", "resolved": "api.log",
                         "found": True, "reason": "test"}],
            "low": [],
        }))

    @staticmethod
    def _fmt_err(result) -> str:
        return (
            f"perform_rca.py exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout[:2000]}\n"
            f"--- stderr ---\n{result.stderr[:2000]}"
        )


@pytest.mark.unit
@_SKIP_VENDOR
class TestPerformRcaReduce:
    """Tests for perform_rca.py --mode reduce (hierarchical summary batching)."""

    def test_single_summary_is_final(self, job_dir):
        """One summary file → single batch with is_final=true."""
        self._write_state(job_dir)
        summary = job_dir / "chunk_summary_high_1.md"
        summary.write_text("## RCA Summary\nThe etcd leader election timed out.\n")

        result = _run_script("perform_rca.py", [
            "--job-dir", str(job_dir), "--priority", "high",
            "--mode", "reduce", "--level", "1",
            "--summary-files", str(summary),
        ])
        assert result.returncode == 0

        output = _parse_stdout_json(result.stdout)
        assert output["mode"] == "reduce"
        assert output["is_final"] is True
        assert output["batch_count"] == 1

        manifest = json.loads(Path(output["manifest_path"]).read_text())
        assert len(manifest["batches"]) == 1

    def test_large_summaries_split_into_batches(self, job_dir):
        """Summaries exceeding the token budget should be split."""
        self._write_state(job_dir)

        # ~85k tokens each (80k budget → can't fit two in one batch)
        large_text = "etcd leader election timed out " * 30000
        summaries = []
        for i in range(3):
            p = job_dir / f"chunk_summary_high_{i + 1}.md"
            p.write_text(large_text)
            summaries.append(str(p))

        result = _run_script("perform_rca.py", [
            "--job-dir", str(job_dir), "--priority", "high",
            "--mode", "reduce", "--level", "1",
            "--summary-files", *summaries,
        ])
        assert result.returncode == 0

        output = _parse_stdout_json(result.stdout)
        assert output["batch_count"] >= 2, "Expected batching due to token budget"
        assert output["is_final"] is False

    def test_missing_summary_files_exits_with_error(self, job_dir):
        """Reduce mode without --summary-files should exit 1 with error JSON."""
        self._write_state(job_dir)

        result = _run_script("perform_rca.py", [
            "--job-dir", str(job_dir), "--priority", "high",
            "--mode", "reduce",
        ])
        assert result.returncode == 1

        output = _parse_stdout_json(result.stdout)
        assert "error" in output

    @staticmethod
    def _write_state(job_dir: Path):
        (job_dir / "state.json").write_text(json.dumps({
            "job_id": "func0003",
            "job_dir": str(job_dir),
            "cluster_dir": "/tmp/fake",
            "query": "etcd pods not ready",
            "mode": "must-gather",
        }))
