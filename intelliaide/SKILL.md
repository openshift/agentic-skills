---
name: intelliaide
description: Deep troubleshooting and root cause analysis for OpenShift clusters using must-gather archives. Use when the user wants a thorough investigation, deep analysis, or RCA of any cluster issue and has a must-gather available.
---

# IntelliAide RCA Skills

You are the orchestrator of the IntelliAide root-cause analysis pipeline for OpenShift clusters.
You call each IntelliAide component as a separate skill and decide what to run next based on
what each step reports.

**Important:** All LLM reasoning in this pipeline is performed by YOU (the orchestrating agent).
The Python skill scripts handle only pure computation: token estimation, chunking, prompt
formatting, and file I/O.  No script makes an independent LLM call.

---

## When to use IntelliAide

Use IntelliAide whenever the user wants any of the following:

- Deep troubleshooting of a cluster issue using a must-gather archive
- Root cause analysis (RCA) or structured diagnosis of any cluster problem
- Thorough investigation where a quick inspection is not sufficient
- A detailed remediation report with prioritised findings and recommendations

---

## Progress Reporting to the Console

At the **start of the pipeline** (before Step 1), derive the Proposal name and namespace from
the sandbox pod hostname, then annotate the Proposal so progress is visible in the console and
in `oc describe proposal`:

```bash
_PROPOSAL=$(hostname | sed 's/^ls-[^-]*-analysis-//;s/^ls-analysis-//')
_NS="openshift-lightspeed"
```

After **each step** completes, update the progress annotation:

```bash
oc annotate proposal "$_PROPOSAL" -n "$_NS" \
  intelliaide.io/progress="<message>" --overwrite 2>/dev/null || true
```

Use these messages at each step:

- Before Step 1: `"IntelliAide: validating must-gather data at /data/input (PVC)"`
- After Step 1:  `"IntelliAide: must-gather ready — preparing file selection"`
- After Step 2a: `"IntelliAide: file selection prompt ready — selecting files"`
- After Step 2b: `"IntelliAide: file selection complete (high=N, medium=N, low=N) — running ML analysis"`
- After Step 3:  `"IntelliAide: ML analysis complete — preparing RCA chunks (high priority)"`
- After Step 4a: `"IntelliAide: RCA chunks ready (N chunks) — analyzing"`
- After Step 4b: `"IntelliAide: chunk analysis complete — batching for synthesis"`
- After Step 5:  `"IntelliAide: high-priority RCA complete"`
- After medium/low passes (if run): `"IntelliAide: medium-priority RCA complete"` / `"IntelliAide: low-priority RCA complete"`
- At the very end: `"IntelliAide: pipeline complete — mapping to output schema"`

If `oc annotate` fails, ignore it and continue — it is non-critical.

---

## Step-by-Step Orchestration

Work through the steps below **in order**.  After each command, parse the JSON line printed to
stdout and decide whether to continue.

### Step 1 — Validate the pre-populated must-gather PVC

```
python /app/skills/intelliaide/extract_cluster.py --query "<problem statement>"
```

The script immediately validates the must-gather data mounted from the PVC at `/data/input`.
The PVC must be pre-populated with diagnostic data before the Proposal is created — the operator
mounts it read-only into the sandbox pod automatically. No manual `oc cp` is required.

Capture `job_dir` and `cluster_dir` from the output JSON.  If `success=false`, **stop
immediately** and return the following error JSON — do not proceed to Step 2:

```json
{"success": false, "options": [], "error": "<error message from extract_cluster.py output>"}
```

> **CRITICAL — buffer safety rule (applies to ALL steps):**
> Never `cat`, `ls -R`, `find`, `grep -r`, or otherwise read must-gather bundle files
> directly after this step. Must-gather bundles are gigabytes of raw data. Reading any
> part of the bundle inline overflows the SDK's 1 MB message buffer and crashes the session.
> All file access is performed exclusively through the Python skill scripts in Steps 2–5,
> which chunk the data safely. The only `cat` calls permitted are:
>
> - `cat <prompt_path>` in Step 2b (the generated file-selection prompt — ≤ 512 KB)
> - `cat <chunk_file>` in Step 4b (individual chunk files — bounded by perform_rca.py)
> - `cat <batch summary file>` in Step 5b (bounded summaries)
> - `cat <job_dir>/rca_<priority>.json` in Step 6 (final report only)
>
> Do **not** deviate from this list.

---

### Step 2 — Select relevant files

#### Step 2a — Prepare the file-selection prompt (Python, no LLM)

```
python /app/skills/intelliaide/select_files.py --job-dir <job_dir>
```

Output JSON:

```json
{"prompt_path": "<job_dir>/file_selection_prompt.md", "cluster_dir": "...", "docs_dir": "...", "has_docs": true}
```

#### Step 2b — Perform file selection (YOU reason inline)

```
cat <prompt_path>
```

Read this **generated prompt file** (it contains a file-tree index, not raw must-gather data —
it is safe to cat).  Then select the most relevant must-gather files for the problem, grouped
by priority (high / medium / low).  Do **not** cat any of the listed must-gather files themselves.

Write `<job_dir>/file_selection.json` with the following schema:

```json
{
  "query":            "<original query>",
  "cluster_dir":      "<cluster_dir>",
  "problem_category": "<short category, e.g. etcd / networking / storage>",
  "high":   [{"original": "path/to/file", "resolved": "path/to/file", "found": true, "reason": "why high priority"}],
  "medium": [...],
  "low":    [...]
}
```

Rules:

- Include both `current.log` and `previous.log` for relevant pod log directories.
- Set `"resolved"` equal to `"original"` (path verification happens downstream).
- Set `"found": true` for all entries (downstream analyze_data.py checks actual existence).
- Aim for 5–20 high-priority files, fewer medium/low.

---

### Step 3 — Analyze data with ML (Python, no LLM)

Run for each priority tier that has files (high first, then medium/low only if needed):

```
python /app/skills/intelliaide/analyze_data.py --job-dir <job_dir> --priority high
```

Capture `priority`, `yaml_files`, `log_files` from output.

---

### Step 4 — Map phase: prepare and analyze RCA chunks

#### Step 4a — Prepare chunk prompt files (Python, no LLM)

```
python /app/skills/intelliaide/perform_rca.py --job-dir <job_dir> --priority high
```

Output JSON:

```json
{"mode": "chunks", "priority": "high", "chunk_count": N, "manifest_path": "...", "has_medium": true, "has_low": false}
```

Capture `chunk_count`, `manifest_path`, `has_medium`, `has_low`.

If `chunk_count == 0`: stop and return an error JSON — IntelliAide found no data to analyze
and cannot proceed without must-gather content:

```json
{"success": false, "options": [], "error": "No data chunks found for priority <priority> — must-gather content may be empty or unreadable"}
```

#### Step 4b — Analyze each chunk (YOU reason inline)

For each entry in `manifest["chunk_files"]`:

```
cat <entry["path"]>
```

After reading the chunk, write a concise root-cause summary (≤600 words) for this chunk to:

```
<job_dir>/chunk_summary_high_<n>.md
```

where `<n>` is the 1-based index of the chunk.  Focus on:

- Specific error patterns and their likely cause
- Key files or components implicated
- Any timestamps or chronology relevant to the problem

Keep summaries concise — they are fed into the reduce phase.

---

### Step 5 — Reduce phase: batch and synthesize (iterative until is_final)

#### Step 5a — Prepare reduce batches (Python, no LLM)

After ALL chunk summaries have been written, call:

```
python /app/skills/intelliaide/perform_rca.py \
  --job-dir <job_dir> \
  --priority high \
  --mode reduce \
  --level 1 \
  --summary-files <job_dir>/chunk_summary_high_1.md \
                  <job_dir>/chunk_summary_high_2.md \
                  ... (all chunk summary files)
```

Output JSON:

```json
{"mode": "reduce", "priority": "high", "level": 1, "batch_count": N, "is_final": true/false, "manifest_path": "..."}
```

Step 5b — Synthesize each batch (YOU reason inline)

For each batch in `manifest["batches"]`:

```
cat <each file in batch["summary_files"]>
```

Read all summaries in the batch, then write a synthesized analysis to `batch["output_file"]`.

If `is_final=true` (only one batch): this synthesized output is the **final RCA text**.
  → Skip to Step 6.

If `is_final=false` (multiple batches): after writing all batch outputs, call Step 5a again at
the next level:

```
python /app/skills/intelliaide/perform_rca.py \
  --job-dir <job_dir> \
  --priority high \
  --mode reduce \
  --level <level+1> \
  --summary-files <all batch["output_file"] paths from current level>
```

Repeat until `is_final=true`.

---

### Step 6 — Write final RCA output

When Step 5 is complete with `is_final=true`, the last `batch["output_file"]` contains the
final RCA text.

```
cat <final output_file>
```

Write `<job_dir>/rca_high.json`:

```json
{
  "priority":      "high",
  "rca_text":      "<full RCA markdown text>",
  "cost_usd":      0,
  "input_tokens":  0,
  "output_tokens": 0,
  "has_medium":    true,
  "has_low":       false,
  "error":         null
}
```

Set `cost_usd`, `input_tokens`, `output_tokens` to 0 — Claude's usage is tracked at the
operator session level, not inside IntelliAide.

---

### Steps 7–8 (optional) — Medium and Low priority passes

If `has_medium=true` after the high-priority pass, repeat Steps 3–6 with `--priority medium`.
When calling analyze_data.py for medium, prefix your chunk summaries with the high-priority
RCA text as context so the analysis builds on prior findings.

If `has_low=true` after the medium pass, repeat with `--priority low`.

---

### Step 9 — Map final RCA to output schema

Read the final `rca_<last_priority>.json` file:

```
cat <job_dir>/rca_<last_priority>.json
```

The `rca_text` field contains the full markdown RCA report with headings:
`## Root Cause`, `## Key Findings`, `## Recommendations`, `## Chronology`.

Parse those sections and map them to the output schema as described in the
**Output Schema Mapping** section below.

---

## Error Handling

| Situation                                                  | What to do                                                                  |
| ---------------------------------------------------------- | --------------------------------------------------------------------------- |
| `extract_cluster.py` exits non-zero                      | **Stop — return error JSON with the error message. Do not proceed.** |
| `select_files.py` returns no `prompt_path`             | **Stop — return error JSON: file selection prompt is missing**       |
| `file_selection.json` has all-zero counts                | **Stop — return error JSON: no files were selected for analysis**    |
| `analyze_data.py` exits non-zero                         | **Stop — return error JSON for this priority tier**                  |
| `perform_rca.py --mode chunks` returns `chunk_count=0` | **Stop — return error JSON: no data chunks to analyze**              |
| Any step times out                                         | **Stop — return error JSON noting which step timed out**             |

Never fall back to `kubectl`/`oc` commands — the IntelliAide pipeline requires must-gather data.
If any step fails, return a structured error JSON immediately:

```json
{"success": false, "options": [], "error": "<description of what failed and why>"}
```

---

## Output Schema Mapping

After all steps complete, produce one option per major root cause identified in the final
`rca_text`.  Map the RCA sections to the **standard** output fields as follows:

| RCA section heading (in `rca_text`)                     | Standard output field           |
| --------------------------------------------------------- | ------------------------------- |
| `## Root Cause` summary paragraph + `## Key Findings` | `diagnosis.summary`           |
| `## Root Cause` / specific underlying cause             | `diagnosis.rootCause`         |
| Evidence quality (High/Medium/Low)                        | `diagnosis.confidence`        |
| `## Recommendations` section (full markdown)            | `proposal.description`        |
| Individual remediation steps                              | `proposal.actions[]`          |
| Risk level of remediation                                 | `proposal.risk`               |
| Whether the fix is reversible                             | `proposal.reversible`         |
| `## Chronology` section (if present)                    | append to `diagnosis.summary` |

For each option use this structure:

```json
{
  "title": "<short name for the root cause>",
  "diagnosis": {
    "summary": "<executive summary + key findings + chronology if available (full markdown)>",
    "rootCause": "<specific underlying cause in one sentence>",
    "confidence": "High | Medium | Low"
  },
  "proposal": {
    "description": "<full recommendations section in markdown>",
    "actions": [
      {"type": "command | config | patch", "description": "<one concrete step>"}
    ],
    "risk": "Low | Medium | High | Critical",
    "reversible": "Reversible | Irreversible | Partial"
  }
}
```

**Do not** produce an `rcaSummary` top-level key.  All RCA content goes into
`diagnosis` and `proposal` inside each option.  These fields are rendered
with markdown formatting in the console UI.

---

## Final Response Format

After completing Step 9, your **entire response** MUST be raw JSON in exactly
this shape — the operator's HTTP client requires it:

```json
{
  "success": true,
  "options": [
    {
      "title": "...",
      "diagnosis": { "summary": "...", "rootCause": "...", "confidence": "High | Medium | Low" },
      "proposal": {
        "description": "...",
        "actions": [{"type": "...", "description": "..."}],
        "risk": "Low | Medium | High | Critical",
        "reversible": "Reversible | Irreversible | Partial"
      }
    }
  ]
}
```

Rules:

- `success` **MUST** be `true`.
- `options` **MUST** contain at least one entry.  If IntelliAide found no
  anomalies, produce one option titled `"No Issues Found"` with a diagnosis
  summarising what was collected and confirmed healthy, and a proposal with
  `risk: "Low"` and `reversible: "Reversible"`.
- Output **raw JSON only** — no markdown fences, no prose before or after.
