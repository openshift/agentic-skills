#!/usr/bin/env python3
"""
Convert OpenShift AsciiDoc documentation to GitHub-Flavored Markdown.

Usage:
    python convert.py --source-dir ./openshift-docs --output-dir ./docs
    python convert.py --source-dir ./openshift-docs --output-dir ./docs --distro openshift-enterprise
    python convert.py --source-dir ./openshift-docs --output-dir ./docs --topics welcome,installing

Multi-version support:
    python convert.py --source-dir ./openshift-docs --discover-versions 3
    python convert.py --output-dir ./docs --generate-top-index
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml


def sanitize_docbook_xml(xml_path: str) -> None:
    """Fix invalid XML in DocBook output before passing to pandoc.

    Asciidoctor's DocBook 5 backend has bugs that produce malformed XML:
      1. Entity references missing their semicolons — e.g. &gt" instead
         of &gt;" (the semicolon of &gt; is dropped when followed by a
         quote character).
      2. Doubled quote characters in attribute values — e.g.
         xml:id="some-id""> instead of xml:id="some-id">.
    We attempt a stdlib parse first; if it succeeds the file is already
    valid and we skip all fixups.
    """
    raw = Path(xml_path).read_text(encoding="utf-8", errors="replace")

    # Fast path: if the XML parses cleanly, nothing to fix.
    try:
        ET.fromstring(raw)
        return
    except ET.ParseError:
        pass

    fixed = raw

    # Fix 1: Entity references missing their trailing semicolon.
    # Matches &lt, &gt, &amp, &quot, &apos NOT followed by ';'.
    fixed = re.sub(r'&(lt|gt|amp|quot|apos)(?!;)', r'&\1;', fixed)

    # Fix 2: Doubled quotes closing an attribute — e.g. id="value"">
    # Remove the extra quote so it becomes id="value">.
    fixed = re.sub(r'("")(?=>)', '"', fixed)

    Path(xml_path).write_text(fixed, encoding="utf-8")


def parse_distro_map(source_dir: str) -> dict:
    """Parse _distro_map.yml to get product attributes per distro."""
    distro_path = Path(source_dir) / "_distro_map.yml"
    with open(distro_path) as f:
        return yaml.safe_load(f)


def parse_topic_map(source_dir: str, topic_map_file: str = "_topic_map.yml") -> list:
    """Parse _topic_maps/_topic_map.yml to get the doc hierarchy."""
    # The topic map uses --- as record delimiter (multi-document YAML)
    topic_map_path = Path(source_dir) / "_topic_maps" / topic_map_file
    with open(topic_map_path) as f:
        return list(yaml.safe_load_all(f))


def get_distro_attributes(distro_map: dict, distro: str, branch: str = "main") -> dict:
    """Extract product attributes for a given distro and branch."""
    distro_config = distro_map.get(distro, {})
    branches = distro_config.get("branches", {})
    branch_config = branches.get(branch, {})

    return {
        "product-title": distro_config.get("name", "OpenShift Container Platform"),
        "product-version": branch_config.get("name", "4.17"),
        distro: "",  # Set the distro flag (e.g., openshift-enterprise=)
    }


def discover_versions(distro_map: dict, distro: str, count: int) -> list[dict]:
    """Extract the latest N version branches for a distro, sorted descending.

    Returns a list of dicts: [{"version": "4.22", "branch": "enterprise-4.22"}, ...]
    """
    distro_config = distro_map.get(distro, {})
    branches = distro_config.get("branches", {})

    version_entries = []
    for branch_name, branch_config in branches.items():
        version_str = branch_config.get("name", "")
        if not version_str:
            continue
        # Parse version as tuple of ints for proper sorting (e.g., "4.22" → (4, 22))
        try:
            parts = tuple(int(p) for p in version_str.split("."))
        except ValueError:
            continue
        version_entries.append({
            "version": version_str,
            "branch": branch_name,
            "sort_key": parts,
        })

    # Sort descending by version number
    version_entries.sort(key=lambda e: e["sort_key"], reverse=True)

    # Return top N without the internal sort_key
    return [
        {"version": e["version"], "branch": e["branch"]}
        for e in version_entries[:count]
    ]


def generate_top_index(output_dir: str) -> None:
    """Generate top-level index files that link to version subdirectories.

    Scans output_dir for directories matching version patterns (e.g., 4.22)
    and generates:
      - index.md  — Markdown version selector
      - index.html — HTML version selector
      - AGENTS.md — Top-level pointer to version-specific AGENTS.md files
      - viewer.html — Shared viewer (copy from first version dir found)
    """
    output_path = Path(output_dir)

    # Find version subdirectories (match X.Y pattern)
    version_dirs = []
    for entry in output_path.iterdir():
        if entry.is_dir() and re.match(r'^\d+\.\d+$', entry.name):
            version_dirs.append(entry.name)

    # Sort descending by version number
    version_dirs.sort(
        key=lambda v: tuple(int(p) for p in v.split(".")),
        reverse=True,
    )

    if not version_dirs:
        print("No version directories found in output dir.")
        return

    latest = version_dirs[0]

    # --- index.md ---
    md_lines = [
        "# OpenShift Container Platform Documentation",
        "",
        "> Auto-generated Markdown conversion of [openshift/openshift-docs]"
        "(https://github.com/openshift/openshift-docs).",
        "> Designed for AI agent consumption. Updated weekly.",
        "",
        "## Available Versions",
        "",
    ]
    for v in version_dirs:
        label = f"**{v} (latest)**" if v == latest else v
        md_lines.append(f"- [{label}]({v}/index.md)")
    md_lines.append("")
    (output_path / "index.md").write_text("\n".join(md_lines) + "\n")

    # --- index.html ---
    html_items = []
    for v in version_dirs:
        label = f"{v} (latest)" if v == latest else v
        html_items.append(
            f'<li><a href="{v}/index.html">'
            f'OpenShift Container Platform {label}</a></li>'
        )
    html_content = (
        "<!DOCTYPE html>\n<html><head>\n"
        '<meta charset="utf-8">\n'
        "<title>OpenShift Container Platform Documentation</title>\n"
        "<style>\n"
        "  body { font-family: -apple-system, sans-serif; max-width: 900px;"
        " margin: 40px auto; padding: 0 20px; line-height: 1.6; }\n"
        "  a { color: #0366d6; text-decoration: none; }\n"
        "  a:hover { text-decoration: underline; }\n"
        "  li { margin: 8px 0; font-size: 18px; }\n"
        "  blockquote { color: #586069; border-left: 3px solid #ddd;"
        " padding-left: 12px; margin-left: 0; }\n"
        "</style>\n"
        "</head><body>\n"
        "<h1>OpenShift Container Platform Documentation</h1>\n"
        "<blockquote>Auto-generated Markdown conversion of "
        '<a href="https://github.com/openshift/openshift-docs">'
        "openshift/openshift-docs</a>. "
        "Designed for AI agent consumption. Updated weekly.</blockquote>\n"
        "<h2>Available Versions</h2>\n"
        "<ul>\n" + "\n".join(html_items) + "\n</ul>\n"
        "</body></html>\n"
    )
    (output_path / "index.html").write_text(html_content)

    # --- AGENTS.md ---
    agents_lines = [
        "# OpenShift Container Platform Documentation Index",
        "",
        "> IMPORTANT: Prefer retrieval-led reasoning over pre-training-led",
        "> reasoning for OpenShift tasks. Read the referenced files rather",
        "> than relying on training data which may be outdated.",
        "",
        "## Available Versions",
        "",
    ]
    for v in version_dirs:
        agents_lines.append(
            f"- **{v}**: See [{v}/AGENTS.md]({v}/AGENTS.md) for the full "
            f"documentation map"
        )
    agents_lines.append("")
    agents_lines.append(
        f"The latest version is **{latest}**. "
        "Start with that version unless a specific version is requested."
    )
    agents_lines.append("")
    (output_path / "AGENTS.md").write_text("\n".join(agents_lines) + "\n")

    # --- viewer.html ---
    # Copy from the first version directory that has one
    for v in version_dirs:
        src_viewer = output_path / v / "viewer.html"
        if src_viewer.exists():
            shutil.copy2(src_viewer, output_path / "viewer.html")
            break

    print(f"Generated top-level index for versions: {', '.join(version_dirs)}")


def should_include_topic(topic: dict, distro: str) -> bool:
    """Check if a topic should be included for the target distro."""
    distros = topic.get("Distros", "")
    if not distros:
        return True  # No distro filter = include everywhere
    return distro in distros.split(",")


def convert_file(
    source_file: str,
    dest_file: str,
    attributes: dict,
    source_dir: str,
) -> tuple[bool, str, str]:
    """Convert a single AsciiDoc file to Markdown via DocBook intermediate."""
    source_path = Path(source_file)
    dest_path = Path(dest_file)

    if not source_path.exists():
        return False, str(source_path), f"Source file not found: {source_path}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        tmp_xml = tmp.name

    try:
        # Step 1: AsciiDoc → DocBook via asciidoctor
        cmd_asciidoctor = [
            "asciidoctor",
            "-b", "docbook5",
            "--safe-mode", "unsafe",
            "-o", tmp_xml,
        ]
        # Add attributes
        for key, value in attributes.items():
            if value:
                cmd_asciidoctor.extend(["-a", f"{key}={value}"])
            else:
                cmd_asciidoctor.extend(["-a", key])

        cmd_asciidoctor.append(str(source_path))

        result = subprocess.run(
            cmd_asciidoctor,
            capture_output=True,
            text=True,
            cwd=source_dir,
            timeout=60,
        )

        if result.returncode != 0:
            return False, str(source_path), f"asciidoctor error: {result.stderr}"

        # Step 1.5: Sanitize the DocBook XML (fix stray '<'/'>' in text)
        sanitize_docbook_xml(tmp_xml)

        # Step 2: DocBook → GFM Markdown via pandoc
        cmd_pandoc = [
            "pandoc",
            "-f", "docbook",
            "-t", "gfm",
            "--wrap=none",
            "-o", str(dest_path),
            tmp_xml,
        ]

        result = subprocess.run(
            cmd_pandoc,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return False, str(source_path), f"pandoc error: {result.stderr}"

        # Step 3: Post-process the markdown
        content = dest_path.read_text()
        content = post_process_markdown(content)
        dest_path.write_text(content)

        return True, str(source_path), "OK"

    finally:
        if os.path.exists(tmp_xml):
            os.unlink(tmp_xml)


_WRAPPER_DIV_RE = re.compile(
    r'^<div(?:'
    r'\s+wrapper="1"'            # <div wrapper="1" role="...">
    r'|\s+class="(?:title|formalpara)"'  # <div class="title"> / <div class="formalpara">
    r'|\s+role="_additional-resources"'   # <div role="_additional-resources">
    r'|\s+style="padding-left:\d+px"'    # <div style="padding-left:20px">
    r')(?:\s[^>]*)?>$'           # optional extra attrs, closing >
    r'|^<div>$',                 # bare <div> (no attributes)
    re.MULTILINE,
)


def _strip_wrapper_divs(content: str) -> str:
    """Remove wrapper div tags while preserving content.

    Uses a line-based state machine: when a wrapper div opening tag is
    seen, it is removed and a strip-depth counter incremented.  The
    matching </div> (tracked by depth) is also removed.  Functional
    divs like <div class="sourceCode"> are left untouched.

    Title divs have their content converted to bold (**text**).
    """
    lines = content.split("\n")
    out: list[str] = []
    strip_depth = 0
    title_next = False

    for line in lines:
        stripped = line.strip()

        if _WRAPPER_DIV_RE.match(stripped):
            is_title = 'class="title"' in stripped
            strip_depth += 1
            if is_title:
                title_next = True
            continue

        if stripped == "</div>":
            if strip_depth > 0:
                strip_depth -= 1
                continue
            # Non-wrapper closing div — keep it
            out.append(line)
            continue

        if title_next and stripped:
            out.append(f"**{stripped}**")
            title_next = False
            continue

        if not title_next:
            out.append(line)

    return "\n".join(out)


def post_process_markdown(content: str) -> str:
    """Clean up pandoc output artifacts."""
    # Remove empty anchor divs that pandoc sometimes generates
    content = re.sub(r'<div id="[^"]*">\s*</div>\n?', "", content)

    # Strip HTML wrapper divs that pandoc emits from DocBook conversion.
    # These are structural wrappers around markdown content — removing them
    # keeps the content intact while reducing HTML density so file-type
    # detectors (Magika) classify the output as markdown, not HTML/ERB.
    content = _strip_wrapper_divs(content)

    # Clean up excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Fix admonition blocks (NOTE, WARNING, IMPORTANT, TIP, CAUTION)
    for admonition in ["Note", "Warning", "Important", "Tip", "Caution"]:
        content = re.sub(
            rf"\*\*{admonition}\*\*\n\n",
            f"> **{admonition}**: ",
            content,
        )

    # Remove {.title} class annotations pandoc may leave
    content = re.sub(r'\{\.[\w-]+\}', '', content)

    # Strip trailing whitespace
    content = "\n".join(line.rstrip() for line in content.splitlines())

    return content.strip() + "\n"


def collect_topics(
    topics: list,
    base_dir: str,
    distro: str,
) -> list[dict]:
    """Recursively collect all topic files from the topic map."""
    result = []

    for topic in topics:
        if topic is None:
            continue
        if not should_include_topic(topic, distro):
            continue

        sub_topics = topic.get("Topics", [])
        topic_dir = topic.get("Dir", "")
        topic_file = topic.get("File", "")

        current_dir = os.path.join(base_dir, topic_dir) if topic_dir else base_dir

        if topic_file:
            result.append({
                "name": topic.get("Name", ""),
                "file": topic_file,
                "dir": current_dir,
                "source": os.path.join(current_dir, f"{topic_file}.adoc"),
            })

        if sub_topics:
            result.extend(collect_topics(sub_topics, current_dir, distro))

    return result


def generate_agents_md(topic_groups: list, output_dir: str, distro: str) -> None:
    """Generate a compressed pipe-delimited AGENTS.md index for AI agents.

    Follows the Vercel AGENTS.md pattern: a minimal, pointer-based index
    that tells agents exactly which files to retrieve for each topic,
    without embedding full documentation content.
    """
    agents_path = Path(output_dir) / "AGENTS.md"
    lines = [
        "# OpenShift Container Platform Documentation Index",
        "",
        "> IMPORTANT: Prefer retrieval-led reasoning over pre-training-led",
        "> reasoning for OpenShift tasks. Read the referenced files rather",
        "> than relying on training data which may be outdated.",
        "",
        "## How to Use This Index",
        "",
        "This is a compressed documentation map. Each section lists topic",
        "files using pipe-delimited format: `section/subsection:{file1.md,file2.md}`.",
        "Retrieve the specific file you need rather than reading everything.",
        "",
        "Root: ./",
        "",
        "## Documentation Map",
        "",
    ]

    for group in topic_groups:
        if group is None:
            continue
        if not should_include_topic(group, distro):
            continue

        name = group.get("Name", "Untitled")
        group_dir = group.get("Dir", "")
        sub_topics = group.get("Topics", [])

        if not sub_topics:
            continue

        lines.append(f"### {name}")
        lines.append("")

        # Collect files at the group level and in sub-directories
        before = len(lines)
        _render_agents_section(sub_topics, group_dir, distro, lines, output_dir)

        if len(lines) == before:
            # No files existed for this section — remove the heading
            lines.pop()  # blank line after heading
            lines.pop()  # heading itself
        else:
            lines.append("")

    agents_path.write_text("\n".join(lines) + "\n")


def _render_agents_section(
    topics: list, base_path: str, distro: str, lines: list,
    output_dir: str,
) -> None:
    """Recursively render compressed pipe-delimited topic entries.

    Only includes files that actually exist in output_dir so the index
    never references missing documentation.
    """
    # Group files by their directory path
    dir_files: dict[str, list[str]] = {}
    sub_groups: list[tuple[str, str, list]] = []

    for topic in topics:
        if topic is None:
            continue
        if not should_include_topic(topic, distro):
            continue

        topic_dir = topic.get("Dir", "")
        topic_file = topic.get("File", "")
        sub_topics = topic.get("Topics", [])

        current_path = f"{base_path}/{topic_dir}" if topic_dir else base_path

        if topic_file:
            md_name = f"{topic_file}.md"
            full_path = Path(output_dir) / base_path / md_name
            if full_path.exists():
                dir_files.setdefault(base_path, []).append(md_name)

        if sub_topics:
            if topic_dir:
                sub_groups.append((topic.get("Name", ""), current_path, sub_topics))
            else:
                # Inline sub-topics at the same directory level
                _render_agents_section(
                    sub_topics, base_path, distro, lines, output_dir
                )

    # Emit the current directory's files in compressed format
    if base_path in dir_files:
        files_str = ",".join(dir_files[base_path])
        lines.append(f"|{base_path}:{{{files_str}}}")

    # Recurse into sub-directories
    for sub_name, sub_path, sub_topics in sub_groups:
        _render_agents_section(
            sub_topics, sub_path, distro, lines, output_dir
        )


def generate_index(topic_groups: list, output_dir: str, distro: str) -> None:
    """Generate a navigation index.md from the topic map."""
    index_path = Path(output_dir) / "index.md"
    lines = [
        "# OpenShift Container Platform Documentation",
        "",
        "> Auto-generated Markdown conversion of [openshift/openshift-docs]"
        "(https://github.com/openshift/openshift-docs).",
        "> Designed for AI agent consumption. Updated weekly.",
        "",
        "## Table of Contents",
        "",
    ]

    def render_topics(topics, base_path, indent=0):
        for topic in topics:
            if topic is None:
                continue
            if not should_include_topic(topic, distro):
                continue

            name = topic.get("Name", "Untitled")
            topic_dir = topic.get("Dir", "")
            topic_file = topic.get("File", "")
            sub_topics = topic.get("Topics", [])

            current_path = f"{base_path}/{topic_dir}" if topic_dir else base_path
            prefix = "  " * indent

            if topic_file:
                link = f"{current_path}/{topic_file}.md"
                lines.append(f"{prefix}- [{name}]({link})")
            elif topic_dir:
                lines.append(f"{prefix}- **{name}**")

            if sub_topics:
                render_topics(sub_topics, current_path, indent + 1)

    for group in topic_groups:
        if group is None:
            continue
        if not should_include_topic(group, distro):
            continue

        name = group.get("Name", "Untitled")
        group_dir = group.get("Dir", "")
        sub_topics = group.get("Topics", [])

        lines.append(f"### {name}")
        lines.append("")

        if sub_topics:
            render_topics(sub_topics, group_dir, 0)

        lines.append("")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines) + "\n")

    # Generate AGENTS.md — compressed pipe-delimited documentation index
    # for AI agent consumption (inspired by Vercel's AGENTS.md approach).
    generate_agents_md(topic_groups, output_dir, distro)

    # Generate index.html with links pointing to viewer.html for human browsing.
    # Raw .md URLs remain unchanged for AI agents.
    html_lines = []
    for line in lines:
        import html as html_mod
        text = html_mod.escape(line)
        # Convert markdown links: [text](path.md) → <a href="viewer.html?doc=path.md">text</a>
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            r'<a href="viewer.html?doc=\2">\1</a>',
            text,
        )
        if text.startswith("# "):
            html_lines.append(f"<h1>{text[2:]}</h1>")
        elif text.startswith("## "):
            html_lines.append(f"<h2>{text[3:]}</h2>")
        elif text.startswith("### "):
            html_lines.append(f"<h3>{text[4:]}</h3>")
        elif text.startswith("&gt;"):
            html_lines.append(f"<blockquote>{text[4:].strip()}</blockquote>")
        elif text.strip().startswith("- "):
            indent_level = (len(text) - len(text.lstrip())) // 2
            content = text.strip()[2:]
            content = re.sub(
                r'\*\*([^*]+)\*\*',
                r'<strong>\1</strong>',
                content,
            )
            padding = indent_level * 20
            html_lines.append(
                f'<div style="padding-left:{padding}px">'
                f'&bull; {content}</div>'
            )
        elif text.strip():
            html_lines.append(f"<p>{text}</p>")

    html_path = Path(output_dir) / "index.html"
    html_path.write_text(
        "<!DOCTYPE html>\n<html><head>\n"
        '<meta charset="utf-8">\n'
        "<title>OpenShift Container Platform Documentation</title>\n"
        "<style>\n"
        "  body { font-family: -apple-system, sans-serif; max-width: 900px;"
        " margin: 40px auto; padding: 0 20px; line-height: 1.6; }\n"
        "  a { color: #0366d6; text-decoration: none; }\n"
        "  a:hover { text-decoration: underline; }\n"
        "  blockquote { color: #586069; border-left: 3px solid #ddd;"
        " padding-left: 12px; margin-left: 0; }\n"
        "  h3 { margin-top: 24px; margin-bottom: 8px; }\n"
        "</style>\n"
        "</head><body>\n"
        + "\n".join(html_lines)
        + "\n</body></html>\n"
    )

    # Generate viewer.html — renders a .md file for human browsing.
    # Uses marked.js (CDN) to convert markdown to HTML client-side.
    # The raw .md files are untouched and still served as text/markdown.
    viewer_path = Path(output_dir) / "viewer.html"
    viewer_path.write_text(
        '<!DOCTYPE html>\n<html><head>\n'
        '<meta charset="utf-8">\n'
        '<title>OpenShift Docs</title>\n'
        '<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>\n'
        '<style>\n'
        '  body { font-family: -apple-system, sans-serif; max-width: 900px;'
        ' margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #24292e; }\n'
        '  a { color: #0366d6; }\n'
        '  pre { background: #f6f8fa; padding: 16px; border-radius: 6px;'
        ' overflow-x: auto; }\n'
        '  code { background: #f6f8fa; padding: 2px 6px; border-radius: 3px;'
        ' font-size: 85%; }\n'
        '  pre code { background: none; padding: 0; }\n'
        '  blockquote { color: #586069; border-left: 3px solid #ddd;'
        ' padding-left: 12px; margin-left: 0; }\n'
        '  table { border-collapse: collapse; width: 100%; }\n'
        '  th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }\n'
        '  th { background: #f6f8fa; }\n'
        '  #nav { margin-bottom: 20px; font-size: 14px; }\n'
        '  #error { color: #cb2431; }\n'
        '</style>\n'
        '</head><body>\n'
        '<div id="nav"><a href="index.html">← Table of Contents</a>'
        ' | <span id="filepath"></span></div>\n'
        '<div id="content">Loading...</div>\n'
        '<div id="error"></div>\n'
        '<script>\n'
        '  const params = new URLSearchParams(window.location.search);\n'
        '  const doc = params.get("doc");\n'
        '  document.getElementById("filepath").textContent = doc || "";\n'
        '  if (doc) {\n'
        '    document.title = doc.split("/").pop().replace(".md","") + " — OpenShift Docs";\n'
        '    fetch(doc)\n'
        '      .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })\n'
        '      .then(md => { document.getElementById("content").innerHTML = marked.parse(md); })\n'
        '      .catch(e => {\n'
        '        document.getElementById("content").textContent = "";\n'
        '        document.getElementById("error").textContent = "Failed to load: " + doc;\n'
        '      });\n'
        '  } else {\n'
        '    document.getElementById("content").textContent = "No document specified.";\n'
        '  }\n'
        '</script>\n'
        '</body></html>\n'
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenShift AsciiDoc docs to Markdown"
    )
    parser.add_argument(
        "--source-dir",
        help="Path to cloned openshift-docs repo",
    )
    parser.add_argument(
        "--output-dir",
        default="./docs",
        help="Output directory for Markdown files",
    )
    parser.add_argument(
        "--distro",
        default="openshift-enterprise",
        help="Target distro (default: openshift-enterprise)",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Source branch (for version attributes)",
    )
    parser.add_argument(
        "--topic-map",
        default="_topic_map.yml",
        help="Topic map file name (default: _topic_map.yml)",
    )
    parser.add_argument(
        "--topics",
        default="",
        help="Comma-separated list of topic dirs to convert (empty = all)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--discover-versions",
        type=int,
        metavar="N",
        help="Print latest N version branches as JSON and exit",
    )
    parser.add_argument(
        "--generate-top-index",
        action="store_true",
        help="Generate top-level index from version subdirectories and exit",
    )
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)

    # --discover-versions: print version info as JSON and exit
    if args.discover_versions is not None:
        if not args.source_dir:
            print("Error: --source-dir is required with --discover-versions")
            sys.exit(1)
        source_dir = os.path.abspath(args.source_dir)
        distro_map = parse_distro_map(source_dir)
        versions = discover_versions(distro_map, args.distro, args.discover_versions)
        print(json.dumps(versions))
        return

    # --generate-top-index: scan version subdirs and generate top-level indexes
    if args.generate_top_index:
        generate_top_index(output_dir)
        return

    # Normal conversion mode requires --source-dir
    if not args.source_dir:
        print("Error: --source-dir is required for conversion")
        sys.exit(1)

    source_dir = os.path.abspath(args.source_dir)

    # Verify tools are available
    for tool in ["asciidoctor", "pandoc"]:
        if shutil.which(tool) is None:
            print(f"Error: '{tool}' not found in PATH. Please install it.")
            sys.exit(1)

    # Parse configuration
    print("Parsing distro map...")
    distro_map = parse_distro_map(source_dir)
    attributes = get_distro_attributes(distro_map, args.distro, args.branch)

    print("Parsing topic map...")
    topic_groups = parse_topic_map(source_dir, args.topic_map)

    # Filter to specific topics if requested
    filter_topics = set(args.topics.split(",")) if args.topics else None

    if filter_topics:
        topic_groups = [
            g for g in topic_groups
            if g and g.get("Dir", "") in filter_topics
        ]

    # Collect all files to convert
    all_topics = []
    for group in topic_groups:
        if group is None:
            continue
        if not should_include_topic(group, args.distro):
            continue
        group_dir = group.get("Dir", "")
        sub_topics = group.get("Topics", [])
        if sub_topics:
            all_topics.extend(collect_topics(sub_topics, group_dir, args.distro))

    print(f"Found {len(all_topics)} topics to convert")

    # Clean output directory
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    # Convert files in parallel
    successes = 0
    failures = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for topic in all_topics:
            src = os.path.join(source_dir, topic["source"])
            dest = os.path.join(
                output_dir, topic["dir"], f"{topic['file']}.md"
            )
            future = executor.submit(
                convert_file, src, dest, attributes, source_dir
            )
            futures[future] = topic

        for future in as_completed(futures):
            topic = futures[future]
            success, path, message = future.result()
            if success:
                successes += 1
            else:
                failures += 1
                print(f"  FAIL: {path} — {message}")

    print(f"\nConversion complete: {successes} succeeded, {failures} failed")

    # Generate navigation index
    print("Generating index...")
    generate_index(topic_groups, output_dir, args.distro)

    print(f"Output written to {output_dir}/")


if __name__ == "__main__":
    main()
