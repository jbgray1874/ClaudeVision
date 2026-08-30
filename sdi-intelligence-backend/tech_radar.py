#!/usr/bin/env python3
r"""
tech_radar.py — SDI Intelligence AI Tech Radar
================================================

Scans the live web for the newest LLMs, libraries, and AI software relevant to
SDI's AI programme roadmap, assesses each against SDI's specific use cases, and
produces an HTML report for the MD. Flags what is genuinely NEW since the last
run by diffing against a saved snapshot.

Powered by Claude Opus 4.8 with the web search tool, so every finding is grounded
in current web sources rather than stale training data.

USAGE
-----
    # Default: scan the priority categories
    python tech_radar.py

    # Scan every category (slower, more API calls)
    python tech_radar.py --full

    # Scan specific categories only
    python tech_radar.py --categories llms,vision,3d_design

    # Change the "recent" window for the What's New section (default 90 days)
    python tech_radar.py --since-days 60

OUTPUT
------
    HTML report : C:\ClaudeVision\output\reports\tech_radar_<timestamp>.html
    Snapshot    : C:\ClaudeVision\output\reports\.tech_radar_snapshot.json
                  (used to detect what's new on the next run)

REQUIREMENTS
------------
    pip install anthropic
    ANTHROPIC_API_KEY set in environment (already used by the estimating engine).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ── Configuration ────────────────────────────────────────────────────────────

MODEL = "claude-opus-4-8"
# web_search_20250305 is the stable tool. On Opus 4.8 you can switch to
# "web_search_20260209" for dynamic filtering (more accurate, fewer tokens).
WEB_SEARCH_TOOL_VERSION = "web_search_20250305"
MAX_SEARCHES_PER_CATEGORY = 8
MAX_TOKENS = 6000

OUTPUT_ROOT = Path(os.getenv("SDI_OUTPUT_ROOT", r"C:\ClaudeVision\output"))
REPORTS_DIR = OUTPUT_ROOT / "reports"
SNAPSHOT_PATH = REPORTS_DIR / ".tech_radar_snapshot.json"

# SDI's roadmap areas. Each maps a research focus to the specific SDI use case so
# Claude assesses relevance, not just novelty. "priority" categories run by default.
CATEGORIES: Dict[str, Dict] = {
    "llms": {
        "title": "Frontier LLMs",
        "priority": True,
        "focus": (
            "the newest frontier large language models and their latest versions from "
            "Anthropic (Claude), OpenAI (GPT/o-series), Google (Gemini), Meta (Llama), "
            "Mistral, DeepSeek, Alibaba (Qwen), and xAI (Grok). Cover new releases, "
            "context window sizes, reasoning capability, tool use, pricing, and which "
            "are strongest for structured technical reasoning and document understanding."
        ),
        "sdi_use": (
            "SDI uses LLMs as the reasoning core of its AI estimating engine and "
            "co-worker agents (MD Agent, Sales Intelligence, Design Support, Production "
            "Control, Finance Intelligence). Relevance = strong structured reasoning, "
            "long context for full drawing packages, reliable tool use, and good price/"
            "performance for high-volume internal use."
        ),
    },
    "doc_extraction": {
        "title": "Document Extraction & PDF/Drawing Parsing",
        "priority": True,
        "focus": (
            "the best current AI tools and libraries for extracting structured data "
            "from engineering drawings, PDFs, and CAD documents — including OCR, layout "
            "understanding, table extraction, and vision-language models that read "
            "technical drawings. Cover both commercial APIs and open-source libraries."
        ),
        "sdi_use": (
            "SDI's estimating engine parses multi-page PDF drawing packages and DXF files "
            "to extract part numbers, materials, dimensions, BOMs, and operations. "
            "Relevance = accuracy on dense engineering drawings, handling of OCR noise, "
            "and ability to read dimensions and material specs reliably."
        ),
    },
    "vision": {
        "title": "Vision Models & Defect Detection",
        "priority": True,
        "focus": (
            "the latest computer-vision and vision-language models for industrial "
            "inspection, defect detection, geometry recognition from drawings, and "
            "image understanding. Cover both frontier multimodal models and specialised "
            "manufacturing-inspection systems."
        ),
        "sdi_use": (
            "SDI's roadmap includes AI Quality Inspection and reading geometry from "
            "engineering drawings. Relevance = accurate feature/defect detection on "
            "manufactured parts and reliable geometry extraction from 2D drawings."
        ),
    },
    "3d_design": {
        "title": "3D & Generative Design / Text-to-CAD",
        "priority": True,
        "focus": (
            "the newest AI tools for 3D generation, generative design, text-to-CAD, "
            "parametric design automation, NeRF / Gaussian splatting, AI-powered "
            "rendering/visualisation for retail and interior environments, and AI "
            "assistants inside CAD packages (SolidWorks, Fusion, Rhino, Blender). "
            "Cover both research models and commercial products launched recently."
        ),
        "sdi_use": (
            "SDI's 'Design Omniverse' roadmap item covers AI-assisted 3D and concept "
            "design for retail/hospitality brand experiences. Relevance = quality of "
            "generated 3D/concepts, integration with existing CAD, and production-"
            "readiness of output."
        ),
    },
    "geometry": {
        "title": "Geometry & Mathematical Models for Estimating",
        "priority": True,
        "focus": (
            "the newest AI and computational methods for geometry understanding and "
            "automated cost/quantity estimation — including geometric deep learning, "
            "CAD/DXF geometry recognition, feature recognition from drawings, "
            "manufacturing cost-prediction models, computational-geometry and nesting "
            "libraries, and ML approaches to quantity surveying / fabrication estimating. "
            "Cover both research and commercial tools released recently."
        ),
        "sdi_use": (
            "This is the mathematical core of SDI's estimating engine: inferring cut "
            "lengths, bend counts, areas, wire/section lengths and material mass from "
            "drawing geometry, then converting to cost. Relevance = methods that improve "
            "geometry inference accuracy, nesting/material-utilisation, or cost prediction "
            "from comparable historical jobs."
        ),
    },
    "simulation": {
        "title": "Simulation, Digital Twins & NVIDIA Omniverse",
        "priority": True,
        "focus": (
            "the latest developments in NVIDIA Omniverse and OpenUSD, digital-twin "
            "platforms, real-time 3D collaboration, physics simulation, and AI-driven "
            "factory/production simulation. Cover Omniverse updates, USD tooling, and "
            "competing digital-twin and simulation platforms released recently."
        ),
        "sdi_use": (
            "SDI's roadmap includes a 'Design Omniverse' and AI Manufacture & Robotics. "
            "Relevance = real-time collaborative 3D for brand-experience concepts, "
            "digital twins of fabrication processes, and simulation to de-risk builds "
            "before they hit the shop floor. NVIDIA Omniverse is the reference platform "
            "here — assess its fit, cost, and hardware requirements for SDI."
        ),
    },
    "rag": {
        "title": "RAG, Vector DBs & Embeddings",
        "priority": False,
        "focus": (
            "the current best-in-class retrieval-augmented-generation frameworks, vector "
            "databases, embedding models, and document-chatbot platforms. Cover recent "
            "releases and what is considered state of the art now."
        ),
        "sdi_use": (
            "SDI is building RAG chatbots and a 'find comparables' capability that "
            "retrieves similar past jobs to calibrate new estimates. Relevance = "
            "retrieval accuracy over a technical corpus and ease of self-hosting."
        ),
    },
    "agents": {
        "title": "Agentic Frameworks & Orchestration",
        "priority": False,
        "focus": (
            "the newest agentic AI frameworks, multi-agent orchestration tools, and "
            "agent protocols (e.g. MCP — Model Context Protocol, tool-use frameworks, "
            "workflow orchestration). Cover recent releases and adoption trends."
        ),
        "sdi_use": (
            "SDI's co-worker agents need reliable orchestration, tool use, and "
            "integration with internal systems (Sage X3, BrightHR, SQL). Relevance = "
            "production reliability, observability, and integration breadth."
        ),
    },
    "scheduling": {
        "title": "Production Scheduling & Optimisation AI",
        "priority": False,
        "focus": (
            "the latest AI and optimisation tools for manufacturing production "
            "scheduling, capacity planning, and shop-floor sequencing. Cover both "
            "ML-based approaches and modern solver/optimisation libraries."
        ),
        "sdi_use": (
            "SDI's roadmap includes AI Production Scheduling for its fabrication shop. "
            "Relevance = suitability for job-shop scheduling with mixed steel/joinery "
            "work and integration with existing systems."
        ),
    },
    "voice": {
        "title": "Voice & Speech Models",
        "priority": False,
        "focus": (
            "the newest speech-to-text, text-to-speech, and real-time voice AI models "
            "and APIs. Cover latency, quality, language support, and recent releases."
        ),
        "sdi_use": (
            "SDI's roadmap includes AI Voice Agents. Relevance = natural real-time "
            "conversation quality, latency, and cost for customer-facing use."
        ),
    },
}


# ── Anthropic client ───────────────────────────────────────────────────────────

def _get_client():
    try:
        import anthropic
    except ImportError:
        sys.exit("ERROR: the 'anthropic' package is not installed.\n"
                 "Run:  pip install anthropic")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ERROR: ANTHROPIC_API_KEY is not set in the environment.")
    return anthropic.Anthropic(api_key=key)


def _research_category(client, key: str, cfg: Dict, since_days: int,
                       previously_seen: List[str]) -> Dict:
    """Run one web-search-backed research pass for a single category."""
    seen_note = ""
    if previously_seen:
        seen_note = (
            "\n\nThe following items were already reported in the previous radar run. "
            "Treat these as known — only mark something as NEW if it is genuinely a "
            "newer release or was not in this list:\n- "
            + "\n- ".join(previously_seen[:40])
        )

    prompt = f"""You are preparing a section of an internal AI Tech Radar for SDI Displays, a
design-led manufacturer of retail and hospitality brand experiences in the UK.

Research the live web for: {cfg['focus']}

SDI's specific use case for this area:
{cfg['sdi_use']}

Today's date is {_dt.date.today().isoformat()}. Pay particular attention to anything
released or significantly updated in the last {since_days} days.{seen_note}

Produce a concise briefing in GitHub-flavoured Markdown with exactly these parts:

### What's new (last {since_days} days)
A short bulleted list of genuinely recent releases/updates relevant to SDI. If nothing
significant is new in the window, say so in one line.

### Current best options for SDI
A markdown table with columns: | Tool / Model | Vendor | Why it matters for SDI | Ring |
where Ring is one of ADOPT, TRIAL, ASSESS, or HOLD (ThoughtWorks-style):
- ADOPT = proven, use it now
- TRIAL = worth piloting on a real SDI job
- ASSESS = promising, keep watching
- HOLD = not yet, or not a fit
List 4-7 rows, most relevant first.

### Recommendation for SDI
2-3 sentences: what you would actually do next for this area.

At the very end, on its own line, output a compact JSON array of the distinct tool/model
names you covered, wrapped in <ITEMS>...</ITEMS> tags, e.g.
<ITEMS>["Claude Opus 4.8", "GPT-5.1", "Gemini 3 Pro"]</ITEMS>

Keep the whole section tight and decision-useful. Cite sources inline where it matters.
Paraphrase everything — never quote more than a few words from any source."""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[{
            "type": WEB_SEARCH_TOOL_VERSION,
            "name": "web_search",
            "max_uses": MAX_SEARCHES_PER_CATEGORY,
        }],
    )

    # Concatenate all text blocks (web search interleaves tool_use / tool_result blocks)
    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
    ).strip()

    # Extract the <ITEMS> JSON list for snapshot diffing
    items: List[str] = []
    m = re.search(r"<ITEMS>(.*?)</ITEMS>", text, re.DOTALL)
    if m:
        try:
            items = [str(x) for x in json.loads(m.group(1).strip())]
        except Exception:
            items = []
        text = text[:m.start()].rstrip()  # drop the machine block from display

    # Count how many searches were actually run (nice to show in the report)
    searches = sum(
        1 for b in resp.content if getattr(b, "type", "") == "server_tool_use"
    )

    return {"key": key, "title": cfg["title"], "markdown": text,
            "items": items, "searches": searches}


# ── Markdown → HTML (small, dependency-free) ─────────────────────────────────────

def _md_to_html(md: str) -> str:
    """Minimal markdown renderer: h3, tables, bullets, bold, inline code, links."""
    lines = md.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Tables
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2  # skip header + separator
            rows = []
            while i < len(lines) and "|" in lines[i]:
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_inline(h)}</th>" for h in header)
                       + "</tr></thead><tbody>")
            for r in rows:
                cells = "".join(f"<td>{_ring_badge(_inline(c))}</td>" for c in r)
                out.append(f"<tr>{cells}</tr>")
            out.append("</tbody></table>")
            continue

        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:].strip())}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:].strip())}</h2>")
        elif line.strip().startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.strip():
            out.append(f"<p>{_inline(line.strip())}</p>")
        i += 1
    return "\n".join(out)


def _inline(s: str) -> str:
    s = _html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _ring_badge(cell: str) -> str:
    for ring, css in (("ADOPT", "adopt"), ("TRIAL", "trial"),
                      ("ASSESS", "assess"), ("HOLD", "hold")):
        if cell.strip().upper() == ring:
            return f'<span class="ring ring-{css}">{ring}</span>'
    return cell


# ── HTML report ──────────────────────────────────────────────────────────────────

def _build_html(sections: List[Dict], new_items: Dict[str, List[str]],
                run_ts: str, since_days: int) -> str:
    total_searches = sum(s["searches"] for s in sections)
    total_new = sum(len(v) for v in new_items.values())

    new_block = ""
    if total_new:
        rows = ""
        for sec in sections:
            n = new_items.get(sec["key"], [])
            if n:
                rows += (f'<tr><td>{_html.escape(sec["title"])}</td>'
                         f'<td>{", ".join(_html.escape(x) for x in n)}</td></tr>')
        new_block = f"""
        <div class="newbox">
          <h2>🆕 New since last run ({total_new})</h2>
          <table><thead><tr><th>Area</th><th>New items</th></tr></thead>
          <tbody>{rows}</tbody></table>
        </div>"""
    else:
        new_block = ('<div class="newbox muted">No previous snapshot to compare '
                     'against — everything in this report is the current baseline. '
                     'The next run will highlight what has changed.</div>')

    body = ""
    for sec in sections:
        body += (f'<section><div class="sec-head"><h2>{_html.escape(sec["title"])}</h2>'
                 f'<span class="searches">{sec["searches"]} web searches</span></div>'
                 f'{_md_to_html(sec["markdown"])}</section>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SDI AI Tech Radar — {run_ts}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#0d0d0f; --surface:#17171b; --surface-2:#1d1d22;
    --line:#2a2a31; --line-soft:#202026;
    --ink:#f3f2ee; --ink-dim:#a3a3aa; --ink-faint:#6b6b73;
    --accent:#ffd400; --accent-deep:#e6be00;
    --ok:#5fd08a; --warn:#ff9d42; --info:#6db3ff;
    --r:4px;
    --mono:'JetBrains Mono',ui-monospace,monospace;
    --disp:'Archivo',sans-serif;
    --body:'Hanken Grotesk',sans-serif;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family:var(--body); color:var(--ink); background:var(--bg);
    font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased;
    background-image:
      radial-gradient(900px 500px at 88% -8%, rgba(255,212,0,.06), transparent 60%),
      radial-gradient(700px 600px at -5% 110%, rgba(255,212,0,.03), transparent 55%);
    min-height:100vh;
  }}
  ::selection {{ background:var(--accent); color:#000; }}
  .wrap {{ max-width:980px; margin:0 auto; padding:44px 28px 80px; }}

  header.top {{ border-bottom:1px solid var(--line); padding-bottom:22px; margin-bottom:8px; }}
  .kicker {{ font-family:var(--mono); font-size:11px; letter-spacing:.18em;
            color:var(--accent); text-transform:uppercase; }}
  header.top h1 {{ font-family:var(--disp); font-weight:800; font-size:32px;
                  letter-spacing:-.02em; margin:8px 0 6px; line-height:1.04; }}
  .sub {{ color:var(--ink-dim); font-size:14px; }}
  .meta {{ display:flex; gap:22px; flex-wrap:wrap; font-family:var(--mono);
           font-size:11.5px; color:var(--ink-faint); margin-top:14px; letter-spacing:.04em; }}
  .meta b {{ color:var(--ink-dim); font-weight:500; }}
  .legend {{ font-size:12px; color:var(--ink-faint); margin-top:14px; display:flex;
            gap:14px; flex-wrap:wrap; align-items:center; }}

  .newbox {{ background:var(--surface); border:1px solid var(--line);
            border-left:2px solid var(--accent); border-radius:var(--r);
            padding:18px 20px; margin:26px 0; }}
  .newbox.muted {{ border-left-color:var(--ink-faint); color:var(--ink-dim); }}
  .newbox h2 {{ font-family:var(--disp); font-weight:700; font-size:15px;
               letter-spacing:.06em; text-transform:uppercase; margin:0 0 10px; color:var(--ink); }}

  section {{ background:var(--surface); border:1px solid var(--line);
            border-radius:var(--r); padding:8px 24px 22px; margin:22px 0; }}
  .sec-head {{ display:flex; align-items:baseline; justify-content:space-between;
              border-bottom:1px solid var(--line-soft); margin-bottom:8px; }}
  .sec-head h2 {{ font-family:var(--disp); font-weight:700; font-size:18px;
                 letter-spacing:.01em; margin:18px 0 12px; color:var(--ink); }}
  .searches {{ font-family:var(--mono); font-size:11px; color:var(--ink-faint); }}
  h3 {{ font-family:var(--mono); font-size:11px; letter-spacing:.16em; text-transform:uppercase;
       margin:20px 0 8px; color:var(--accent); }}
  p {{ margin:8px 0; color:var(--ink-dim); }}
  ul {{ margin:8px 0; padding-left:22px; }}
  li {{ margin:5px 0; color:var(--ink-dim); }}
  strong {{ color:var(--ink); font-weight:600; }}
  em {{ color:var(--ink); font-style:italic; }}

  table {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:13.5px; }}
  th,td {{ text-align:left; padding:9px 11px; border-bottom:1px solid var(--line-soft);
          vertical-align:top; color:var(--ink-dim); }}
  th {{ background:var(--surface-2); color:var(--ink); font-family:var(--mono);
       font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; font-weight:500; }}
  code {{ background:var(--bg); border:1px solid var(--line-soft); color:var(--accent);
         font-family:var(--mono); padding:1px 6px; border-radius:3px; font-size:12.5px; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}

  .ring {{ display:inline-block; padding:2px 10px; border-radius:100px; font-family:var(--mono);
          font-size:10.5px; font-weight:700; letter-spacing:.08em; white-space:nowrap; }}
  .ring-adopt {{ background:var(--ok); color:#08130c; }}
  .ring-trial {{ background:var(--accent); color:#1a1500; }}
  .ring-assess {{ background:var(--info); color:#03152b; }}
  .ring-hold {{ background:transparent; color:var(--ink-faint); border:1px solid var(--line); }}

  footer {{ color:var(--ink-faint); font-size:11.5px; margin-top:34px; text-align:center;
           font-family:var(--mono); letter-spacing:.03em; line-height:1.7; }}
  footer code {{ font-size:11px; }}
</style></head>
<body><div class="wrap">
  <header class="top">
    <div class="kicker">we.are.sdi.</div>
    <h1>SDI AI Tech Radar</h1>
    <div class="sub">Experiences. Designed &amp; Made. — AI Programme intelligence scan</div>
    <div class="meta">
      <span><b>Generated</b> {run_ts}</span>
      <span><b>Model</b> {MODEL}</span>
      <span><b>Web searches</b> {total_searches}</span>
      <span><b>Recency window</b> {since_days} days</span>
    </div>
    <div class="legend">
      <span class="ring ring-adopt">ADOPT</span> use now
      <span class="ring ring-trial">TRIAL</span> pilot on a real job
      <span class="ring ring-assess">ASSESS</span> watch closely
      <span class="ring ring-hold">HOLD</span> not yet / not a fit
    </div>
  </header>
  {new_block}
  {body}
  <footer>Generated by tech_radar.py — grounded in live web search via Claude Opus 4.8.<br>
  AI-assisted research; verify before procurement decisions.</footer>
</div></body></html>"""


# ── Snapshot diff ────────────────────────────────────────────────────────────────

def _load_snapshot() -> Dict[str, List[str]]:
    if SNAPSHOT_PATH.exists():
        try:
            return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_snapshot(sections: List[Dict]) -> None:
    snap = {s["key"]: s["items"] for s in sections}
    SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="SDI AI Tech Radar")
    ap.add_argument("--full", action="store_true",
                    help="Scan every category (default: priority categories only)")
    ap.add_argument("--categories", type=str, default="",
                    help="Comma-separated category keys to scan "
                         f"(available: {', '.join(CATEGORIES)})")
    ap.add_argument("--since-days", type=int, default=90,
                    help="Recency window for the What's New section (default 90)")
    args = ap.parse_args()

    if args.categories:
        keys = [k.strip() for k in args.categories.split(",") if k.strip() in CATEGORIES]
        if not keys:
            sys.exit(f"No valid categories. Available: {', '.join(CATEGORIES)}")
    elif args.full:
        keys = list(CATEGORIES)
    else:
        keys = [k for k, c in CATEGORIES.items() if c.get("priority")]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    client = _get_client()
    previous = _load_snapshot()

    print(f"SDI AI Tech Radar — scanning {len(keys)} categor"
          f"{'y' if len(keys) == 1 else 'ies'}: {', '.join(keys)}\n")

    sections: List[Dict] = []
    new_items: Dict[str, List[str]] = {}
    for k in keys:
        print(f"  • {CATEGORIES[k]['title']} ... ", end="", flush=True)
        try:
            sec = _research_category(client, k, CATEGORIES[k], args.since_days,
                                     previous.get(k, []))
            sections.append(sec)
            prev_set = {x.lower() for x in previous.get(k, [])}
            fresh = [x for x in sec["items"] if x.lower() not in prev_set]
            if previous.get(k):  # only flag "new" if we have a prior baseline
                new_items[k] = fresh
            print(f"done ({sec['searches']} searches, {len(sec['items'])} items)")
        except Exception as e:
            print(f"FAILED: {e}")

    if not sections:
        sys.exit("No sections produced — check API key and connectivity.")

    run_ts = _dt.datetime.now().strftime("%d %b %Y %H:%M")
    html = _build_html(sections, new_items, run_ts, args.since_days)

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"tech_radar_{stamp}.html"
    out.write_text(html, encoding="utf-8")
    _save_snapshot(sections)

    print(f"\nReport written: {out}")
    print(f"Snapshot saved: {SNAPSHOT_PATH}")
    print("Open the report in a browser, or browse to it from the portal "
          "Status Reports / Files section.")


if __name__ == "__main__":
    main()
