# `blender` — image-and-scene DCC bridge

This module is the glue that lets an AI assistant **drive a live Blender session**:
introspect the scene graph, manipulate objects, execute Python operations, and render
previews — all from an MCP tool call. The scope here is **interactive only**: the
assistant connects to a running Blender GUI instance over a loopback socket, reads
and edits the scene, and fires renders into a folder you choose. The unattended
headless path — `blender --background --python` driven by the self-correction loop —
is a **Phase 2** item (forward-referenced here; it does not exist yet).

## The MCP bridge

| | |
|---|---|
| **Server** | official `lab/blender_mcp` (Blender Foundation) — Gitea `projects.blender.org` |
| **Pinned** | `v1.0.0` = commit `03004fd0216bfe5e0a3d9ac9b47d5efadc3d78c4` |
| **License** | GPL-3.0-or-later · runs 100% locally (loopback `127.0.0.1:9876`) |
| **Transport** | stdio (Claude launches it) → TCP socket → Blender addon |
| **Tools** | 26: scene introspection, object ops, code-exec, render, screenshots, doc search |

> **Why `lab/blender_mcp` and not `ahujasid/blender-mcp`?** The Blender Foundation
> server is first-party, carries zero telemetry (deps are exactly `docutils`,
> `mcp[cli]`, and `pyyaml`), and is headless-capable. The 22.6k-star community fork
> is GUI-only, ships opt-out Supabase telemetry with a bloated dependency chain, and
> had a live arbitrary-file-read bug in the wild — none of that is acceptable for a
> public, security-audited pipeline.

## Activate it

Prerequisites: **[Astral `uv`](https://docs.astral.sh/uv/)** installed and on your
`PATH`; **Blender ≥ 5.1.0** with **online access enabled** (`Edit → Preferences →
System → Network → Allow Online Access`).

1. **Install the Blender addon.** Clone (or download) `lab/blender_mcp` at the pinned
   commit `03004fd…`. Install `addon/blender_mcp_addon/` via
   `Edit → Preferences → Add-ons → Install from Disk`. Enable it. The addon
   auto-starts the loopback socket (`127.0.0.1:9876`) on enable — no extra step needed.

2. **Register the MCP server.** The server entry lives in
   [`../../.mcp.json`](../../.mcp.json) and is launched by Claude Code as:
   ```
   uv run --from git+https://projects.blender.org/lab/blender_mcp@03004fd0216bfe5e0a3d9ac9b47d5efadc3d78c4 blender-mcp
   ```
   Never use `uvx blender-mcp` — the PyPI package under that name is a **different,
   rejected server** (see security notes below).

3. **Approve and confirm.** In Claude Code run **`/mcp`**, approve the `blender` server
   (project-scoped servers require a one-time approval). Confirm: `/mcp` should show
   `blender` **Connected** with 26 tools. Ask the assistant to call
   `get_scene_info` — it should return the active Blender scene, proving the bridge
   reached the addon.

## GUI-only caveat — two execution paths

The MCP bridge requires Blender's **GUI to be running** and the addon enabled; there
is no background-mode equivalent in this module today. The unattended, render-farm
style path — `blender --background --python <script>` with **Cycles (CUDA/OptiX)** —
will be wired into the self-correction loop as a Phase 2 render backend. When that
lands it will live here alongside the interactive bridge; for now, keep a Blender
window open and the addon active for any MCP-assisted work.

## Security audit (v1.0.0) & per-tool gates

**Verdict:** safe-with-precautions — official Blender Foundation server
(`lab/blender_mcp` @ v1.0.0, GPL-3.0); deps are exactly `docutils`/`mcp[cli]`/`pyyaml`
with **zero telemetry** and no Supabase/storage3/pyiceberg, confirming this is NOT
`ahujasid/blender-mcp`. No outbound network in the MCP server or the addon.
Loopback-only TCP bridge (`BLENDER_MCP_HOST`/`PORT`, default localhost:9876), with
the documented exception of an **opt-in HTTP transport (`-t http`, default OFF) that
disables DNS-rebinding protection and uses wildcard CORS — never enable it**.
`execute_blender_code*` are arbitrary-Python RCE behind only a self-described "weak
sandbox" (Tier 1); `render_*_to_path` and the `*_for_cli` tools take caller
filesystem paths (Tier 2).

### Per-tool permission gates

| Tier | Policy | Tools |
|---|---|---|
| **1 — always per-call approval (RCE)** | require explicit approval on every call | `execute_blender_code`, `execute_blender_code_for_cli` |
| **2 — approval + path allowlist** | require approval; paths must be under the project render output directory | `render_viewport_to_path`, `render_thumbnail_to_path`, the 5 `get_blendfile_summary_*_for_cli` tools (they spawn headless Blender on a caller-supplied `.blend` path) |
| **3 — auto-allow (read-only)** | frictionless; no side-effects | scene/object summaries, screenshots, jumps, `search_api_docs` / `search_manual_docs`, `get_python_api_docs` |

Gates are enforced in [`../../.claude/settings.json`](../../.claude/settings.json).

### Hard rules

- **Loopback-only binding.** Never bind the socket to a non-loopback address.
- **Never pass `-t http`.** The HTTP transport disables DNS-rebinding protection and
  opens wildcard CORS — it is incompatible with the security model of this repo.
- **Never open untrusted `.blend` files in an MCP session.** Blender's
  auto-run-script feature means a malicious `.blend` file is a code-execution
  payload — the same class of risk as a malicious Python script.
- **Pin from commit, never `uvx blender-mcp`.** The PyPI package `blender-mcp` is a
  different server that was rejected during audit. Always launch from the pinned
  `projects.blender.org` git ref.
- **Re-audit on every pin bump.** When the pin is advanced, re-run the full audit
  against the diff before committing. Runbook: [`../../docs/UPDATING.md`](../../docs/UPDATING.md).

## Tool surface (highlights)

The official server exposes **no high-level object-CRUD tools** — scene mutation is done by
running Python through `execute_blender_code`. The 26 tools group as:

- **Introspect (read-only):** `get_objects_summary`, `get_object_detail_summary`,
  `get_blendfile_summary_datablocks`, `get_blendfile_summary_missing_files`,
  `get_blendfile_summary_of_linked_libraries`, `get_blendfile_summary_path_info`,
  `get_blendfile_summary_usage_guess`
- **Screenshots (read-only):** `get_screenshot_of_area_as_image`,
  `get_screenshot_of_window_as_image`, `get_screenshot_of_window_as_json`
- **Navigate (read-only):** `jump_to_tab_by_name`, `jump_to_tab_by_space_type`,
  `jump_to_view3d_object_by_name`, `jump_to_view3d_object_data_by_name`
- **Docs / search (read-only):** `search_api_docs`, `search_manual_docs`, `get_python_api_docs`
- **Render (Tier 2 — writes to a caller path):** `render_viewport_to_path`, `render_thumbnail_to_path`
- **Headless `*_for_cli` (Tier 2 — spawn `blender --background` on a caller `.blend`):**
  `get_blendfile_summary_datablocks_for_cli`, `get_blendfile_summary_missing_files_for_cli`,
  `get_blendfile_summary_of_linked_libraries_for_cli`, `get_blendfile_summary_path_info_for_cli`,
  `get_blendfile_summary_usage_guess_for_cli`
- **Code-exec (Tier 1 — RCE):** `execute_blender_code`, `execute_blender_code_for_cli`
