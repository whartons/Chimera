# `cad` — parametric CAD bridge

This module is the glue that lets an AI assistant **drive a live FreeCAD session**:
create and edit parametric solids, run FEM simulations, export STEP/STL/glTF, and
introspect the document model — all from an MCP tool call. The scope here is
**interactive only**: the assistant connects to a running FreeCAD GUI instance over a
loopback XML-RPC bridge, reads and edits the document, and fires exports into a folder
you choose. The unattended headless path — `FreeCADCmd` driven by the self-correction
loop — is a **Phase 2** item (forward-referenced here; it does not exist yet).

## The MCP bridge

| | |
|---|---|
| **Server** | `neka-nat/freecad-mcp` (GitHub) |
| **Pinned** | commit `63acb30` (= published `0.1.18`) — server + addon share the commit |
| **License** | MIT · runs 100% locally (loopback XML-RPC `127.0.0.1:9875`) |
| **Transport** | stdio (Claude launches it) → XML-RPC → FreeCAD addon |
| **Tools** | 14: parametric object ops, FEM, doc/view introspection, code-exec |

> **Why `neka-nat/freecad-mcp` and not the alternatives?** It is the de-facto
> community standard: actively maintained, MIT, no telemetry, and ~14 tools
> including FEM via CalculiX. Rejected alternatives in brief:
> `contextform/freecad-mcp` has the best install UX and a guard-railed 45-tool
> surface, but code has been quiet for approximately 10 months; `jango-blockchained/mcp-freecad`
> is the only fork with a Mock backend for CI and a headless launcher, but
> `execute_script`/`ide_integration` are unsandboxed RCE, and it has a single quiet
> maintainer with no releases; `bonninr/freecad_mcp` is effectively unmaintained
> for approximately 15 months.

## Activate it

Prerequisites: **[Astral `uv`](https://docs.astral.sh/uv/)** installed and on your
`PATH`; **FreeCAD 1.0 or 1.1** (Python 3.12).

1. **Install the FreeCAD addon.** Copy the `addon/FreeCADMCP/` directory from the
   pinned commit `63acb30` into FreeCAD's user `Mod/` directory. **FreeCAD 1.1 uses a
   versioned data dir** — on Windows that is `%APPDATA%\FreeCAD\v1-1\Mod\FreeCADMCP\`
   (1.0 omits the `v1-1`). If unsure, use **Tools → Open user data directory** in FreeCAD
   and copy into the `Mod/` there. Fully restart FreeCAD.

2. **Start the RPC server.** In FreeCAD, select the **"MCP Addon" workbench** from
   the workbench drop-down. Click the **"Start RPC Server"** toolbar button — this
   binds the loopback listener at `127.0.0.1:9875`. Auto-start is opt-in and
   **default OFF**; the server is only exposed when you click this button.

3. **Register the MCP server.** The server entry lives in
   [`../../.mcp.json`](../../.mcp.json) and is launched by Claude Code as:
   ```
   uvx --from git+https://github.com/neka-nat/freecad-mcp@63acb30 freecad-mcp --host 127.0.0.1
   ```

4. **Approve and confirm.** In Claude Code run **`/mcp`** and approve the `freecad`
   server (project-scoped servers require a one-time approval). Confirm: `/mcp`
   should show `freecad` **Connected** with 14 tools. Smoke-test by calling
   `get_objects` or `list_documents` (Tier 3, read-only) — either should return the
   active FreeCAD document's contents, proving the bridge reached the addon.

## GUI-only caveat — two execution paths

`neka-nat/freecad-mcp` has no headless mode: all work is marshaled onto FreeCAD's
Qt GUI thread, and the RPC server is started from a toolbar button in the running
GUI. There is no background-mode equivalent in this module today. The unattended
path — used by the self-correction loop — will shell out to `FreeCADCmd script.py`
instead (Phase 2). Note that `FreeCADCmd` emits **geometry only** (STEP/STL/glTF —
no headless renderer), so render-for-judge in that path goes through the Blender
Cycles step; keep a FreeCAD window open and the addon active for any MCP-assisted
work until Phase 2 lands.

## Security audit (commit `63acb30`) & per-tool gates

**Verdict:** safe-with-precautions — `neka-nat/freecad-mcp` @ `63acb30` (MIT) has a
clean minimal dep set (`mcp[cli]`, `validators`) with **no telemetry/Supabase/pickle/torch**
and no outbound network; the sole transport is loopback XML-RPC to FreeCAD on
hardcoded `:9875`, a default `127.0.0.1` bind that flips to `0.0.0.0` only on
explicit user opt-in and is still IP-allowlist-filtered (default `127.0.0.1`) via
`verify_request`. The RPC server only starts from a deliberate "Start RPC Server"
toolbar button (auto-start opt-in, default OFF), so nothing is exposed until the
user acts. `execute_code`/`execute_code_async` are `exec(code, globals())` RCE
(Tier 1); `create_object`/`edit_object`/`delete_object` do not eval property values
but present an unbounded `setattr` + `addObject` surface the source can't prove
inert (Tier 1, conservative); `insert_part_from_library` lacks a path-traversal
guard (Tier 2). Not executed during audit — loopback bind + IP filter asserted from
source.

### Per-tool permission gates

| Tier | Policy | Tools |
|---|---|---|
| **1 — always per-call approval (RCE / unbounded mutation)** | require explicit approval on every call | `execute_code`, `execute_code_async`, `create_object`, `edit_object`, `delete_object` |
| **2 — approval + path/host allowlist** | require approval; path/host must be explicitly vetted | `insert_part_from_library` (no path-traversal guard), `run_fem_analysis` |
| **3 — auto-allow (read-only)** | frictionless; no side-effects | `create_document`, `get_view`, `get_objects`, `get_object`, `get_parts_list`, `list_documents`, `reload_document` |

Gates are enforced in [`../../.claude/settings.json`](../../.claude/settings.json).

### Hard rules

- **Loopback-only binding.** Never enable "Remote Connections" in the FreeCAD MCP
  Addon settings — doing so flips the bind to `0.0.0.0` with IP-filter-only access
  and no auth. Keep **Allowed IPs** = `127.0.0.1`.
- **Path-allowlist `insert_part_from_library`.** The tool has no path-traversal
  guard; scope library paths to a known safe directory before approving any call.
- **Pin from commit, never floating tag.** Always launch from the pinned git ref
  `63acb30` so the server cannot change under you.
- **Re-audit on every pin bump.** When the pin is advanced, re-run the full audit
  against the diff before committing. Runbook:
  [`../../docs/UPDATING.md`](../../docs/UPDATING.md).

## Tool surface (highlights)

The server exposes exactly **14 tools**, grouped as:

- **Parametric ops (Tier 1 — mutation):** `create_object`, `edit_object`,
  `delete_object`
- **Documents / introspect (Tier 3 — read-only):** `create_document`,
  `list_documents`, `reload_document`, `get_objects`, `get_object`, `get_view`,
  `get_parts_list`
- **Library / FEM (Tier 2 — path/host approval):** `insert_part_from_library`,
  `run_fem_analysis`
- **Code-exec (Tier 1 — RCE):** `execute_code`, `execute_code_async`
