# `agent` — LLM / MCP orchestration layer

This module is the glue that lets an AI assistant **drive ComfyUI**: introspect
nodes, build/queue workflows, poll progress, fetch outputs, and manage models &
custom nodes. Per the repo philosophy ([../../CLAUDE.md](../../CLAUDE.md)) we
**build on an existing ComfyUI MCP server** rather than reinventing the transport.

## Two layers here
- **The MCP bridge** (below) — the assistant→ComfyUI **transport**: introspect,
  build/queue, poll, fetch.
- **The self-correction loop** — the **orchestration** layer on top: a
  `generate → judge → refine` loop that iterates to a candidate passing a brand/brief
  rubric, with an assistant multi-judge-consensus backend and a headless VLM backend
  (Qwen3-VL-8B-Instruct — recommended via Ollama `--backend api`, with an optional
  ComfyUI judge node) sharing one model-free core (`scripts/agent/`). See
  [`self-correction.md`](self-correction.md) (and the assistant recipe in
  [`../../workflows/agent/README.md`](../../workflows/agent/README.md)).

## The MCP bridge

| | |
|---|---|
| **Server** | [`artokun/comfyui-mcp`](https://github.com/artokun/comfyui-mcp) (npm: `comfyui-mcp`) |
| **Pinned** | `comfyui-mcp@0.18.0` |
| **License** | MIT · **runs 100% locally** (only talks to your ComfyUI over `127.0.0.1`) |
| **Transport** | stdio — Claude Code / Claude Desktop launch it directly |
| **Tools** | ~100: node introspection, arbitrary API-format workflow exec, queue/poll/interrupt, image up/download, model + custom-node management, VRAM control, plus 0.18.0 graph-panel / Civitai helpers |

> **Why not the "official" one?** Comfy-Org only ships a **cloud-only** MCP
> (`cloud.comfy.org/mcp`) — it can't drive a local instance. There is no official
> *local* MCP, so a community server is the only path. `artokun/comfyui-mcp` is
> MIT, actively maintained, and authored by a Comfy-Org ecosystem contributor.

## Activate it

The server is registered at **project scope** in [`../../.mcp.json`](../../.mcp.json),
so anyone who opens this repo in Claude Code gets it. To turn it on:

1. Make sure ComfyUI is running (this repo assumes **`127.0.0.1:8000`** — the
   ComfyUI **Desktop** default; a manual `python main.py` install uses **`8188`**).
2. In Claude Code, run **`/mcp`** and **approve** the `comfyui` server (project-scoped
   servers require a one-time approval), or restart Claude Code.
3. Confirm: `/mcp` should show `comfyui` **Connected** with ~100 tools. Then ask the
   assistant to call `get_system_stats` — it should report your `comfyui_version`
   and GPU, proving the bridge reached ComfyUI.

### Pointing at a different ComfyUI
`COMFYUI_URL` controls the target. The committed config defaults to
`http://127.0.0.1:8000` but honors an override from your environment:
```
# PowerShell, before launching Claude Code:
$env:COMFYUI_URL = "http://127.0.0.1:8188"
```

### Non-Windows hosts
The tracked config uses a Windows `cmd /c` wrapper (required so Claude Code's
shell-less spawn resolves the `npx` shim). On **macOS / Linux**, change the server
entry to:
```json
"command": "npx",
"args": ["-y", "comfyui-mcp@0.18.0"]
```

## Security model — keep secrets OUT of the tracked config
- `.mcp.json` is **committed and public**. It contains only a loopback URL and a
  package name — **no secrets, no machine-specific absolute paths**. Keep it that way.
- **Never** paste an API token directly into `.mcp.json`. If you enable gated
  **CivitAI** model downloads, the server reads `CIVITAI_API_TOKEN` from the
  environment — set it in your shell / OS env (or a gitignored `.env` you load),
  never in a tracked file. See [`../../.env.example`](../../.env.example).
- This server runs with your user privileges and **can install custom nodes,
  download models, and stop/restart ComfyUI**. That power is the point — but treat
  anything you ask it to install as untrusted code, and the pin (`@0.18.0`) stops it
  changing under you.

## Security audit (v0.18.0) & per-tool gates
This repo pins `comfyui-mcp@0.18.0`. The original `0.9.4` adoption was read-through +
adversarially audited; the `0.9.4 → 0.18.0` bump was **re-audited per
[`../../docs/UPDATING.md`](../../docs/UPDATING.md)** — the release notes for every intervening
version plus the install/network-relevant code (`postinstall.mjs`, the dependency manifest, and
the new tools). Verdict: **not malicious** — with the default `npx` + stdio launch (no extra env),
it opens **no socket, no tunnel, no LLM agent, and exfiltrates nothing** (no telemetry, no `eval`;
tokens scoped to their matching service). 0.18.0's newer capabilities — Comfy Cloud mode, the
Civitai MCP hookup, a generic auth header, and a Claude-Agent-SDK session — are all **opt-in**:
env-gated and/or `optionalDependencies` that `NPM_CONFIG_OMIT=optional` never installs, so they
stay inert. The `postinstall` only copies a settings-template file (`.env.example`-style).
The real risk is **capability by design**: a handful of tools (`install_custom_node`,
`apply_manifest`, `install_comfyui`, …) download and **execute third-party Python** inside
ComfyUI — that's the point, but a prompt-injected workflow could abuse it. So:
- **Hardened launch:** [`../../.mcp.json`](../../.mcp.json) sets `NPM_CONFIG_OMIT=optional`
  so the optional `cloudflared` / S3 / Azure / LLM-SDK deps (used only by opt-in features)
  are never installed — the tunnel path is fully inert.
- **Per-call approval gates:** [`../../.claude/settings.json`](../../.claude/settings.json)
  forces an `ask` prompt (uncoverable by a broad allow) on the ~17 code-execution /
  process-control / destructive tools. Read-only + generation tools stay frictionless.
- **Pin + re-audit on update:** never track `@latest`. A **scheduled weekly job**
  ([`../../.github/workflows/update-check.yml`](../../.github/workflows/update-check.yml)) flags in an
  issue when the pin falls behind upstream; the pin is advanced only after a fresh **manual re-audit**
  of the diff (runbook: [`../../docs/UPDATING.md`](../../docs/UPDATING.md)) — so a version bump is
  always reviewed and deliberate, never silent.

## Sibling DCC/CAD bridges

The agent layer doesn't stop at ComfyUI. The same pin + audit + per-tool-gate model also covers
two DCC/CAD applications:

| Bridge | Module | Phase 1 scope |
|--------|--------|---------------|
| **Blender** (`lab/blender_mcp`, Blender Foundation) | [`../blender/`](../blender/README.md) | Interactive/GUI only — assistant drives a live Blender session |
| **FreeCAD** (`neka-nat/freecad-mcp`) | [`../cad/`](../cad/README.md) | Interactive/GUI only — assistant drives a live FreeCAD session |

Both are **pinned to exact commits, audited, and per-tool-gated** via
[`../../.claude/settings.json`](../../.claude/settings.json) — the same security model as the
ComfyUI bridge. **Phase 1 (the MCP bridges) is GUI-only and interactive.** The headless Blender
backend (Phase 2), 3D self-correction over Blender renders (Phase 3,
[`self-correction.md`](self-correction.md) §3D), front-projected albedo texturing (Phase 4a,
`--texture`), all-around multi-view texture (Phase 4b — `finalize-texture`, manual views **and**
`--auto-repaint`), headless FreeCAD geometry (`generate.py cad`), and the **FreeCAD-driven CAD
self-correction loop** (`cad --mode script` + autonomous `auto_generate.py --pipeline cad` via a
provider-agnostic LLM) are all **shipped**. A `--backend api` LLM judge works on every pipeline.

## Practical note: API format vs UI format
`POST /prompt` (what "run a workflow" uses) accepts only the **API/"prompt" JSON**
format, *not* the canvas `workflow.json` (or the graph embedded in a PNG). To get
API format from the UI: **Settings → enable Dev Mode → Workflow → Export (API)**.
The server can also build graphs itself (`create_workflow` / `modify_workflow`) or
extract one from an image (`workflow_from_image`).

## Tool surface (highlights)
- **Introspect:** `get_node_info`, `list_local_models`, `get_embeddings`
- **Build / run:** `create_workflow`, `modify_workflow`, `validate_workflow`, `enqueue_workflow`
- **Monitor / control:** `get_queue`, `get_job_status`, `cancel_job`, `clear_queue`, `clear_vram`
- **Assets:** `upload_image` / `upload_video` / `upload_audio`, `view_image`, `get_image`, `list_output_images`
- **Manage:** `search_models`, `download_model`, `search_custom_nodes`, `get_node_pack_details`
- **Process:** `stop_comfyui`, `start_comfyui`, `restart_comfyui`, `get_logs`, `get_system_stats`
