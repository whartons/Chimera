# `cad` — parametric CAD bridge

This module is the glue that lets an AI assistant **drive a live FreeCAD session**:
create and edit parametric solids, run FEM simulations, export STEP/STL/glTF, and
introspect the document model — all from an MCP tool call. The scope here is
**interactive only**: the assistant connects to a running FreeCAD GUI instance over a
loopback XML-RPC bridge, reads and edits the document, and fires exports into a folder
you choose. For unattended geometry authoring there is a **second, headless path** —
**`generate.py cad`** (see [below](#headless-generatepy-cad-shipped)) — that drives
`FreeCADCmd` as a normal CLI subprocess; the FreeCAD-driven self-correction loop is still
roadmap.

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

## Headless `generate.py cad` (shipped)

The MCP bridge is GUI-only (all work is marshaled onto FreeCAD's Qt thread; the RPC
server starts from a toolbar button). For **unattended geometry authoring**, use the
headless `cad` subcommand instead — it shells `FreeCADCmd <template> <params.json>` as a
normal CLI subprocess (no per-call approval), exactly as `generate.py render` does for
Blender. Runner: [`../../scripts/brandkit/freecad.py`](../../scripts/brandkit/freecad.py);
templates: [`../../workflows/templates/freecad/`](../../workflows/templates/freecad/).

```bash
# author a parametric solid -> STEP (BREP) + STL
python scripts/generate.py cad --shape tube --radius 12 --inner-radius 8 --height 30 --formats step,stl

# box / cylinder / cone / sphere are the other shapes (mm dimensions, sane defaults)
python scripts/generate.py cad --shape cone --radius 20 --radius2 0 --height 40

# convert an existing CAD/mesh file between formats
python scripts/generate.py cad --mode convert --from part.step --formats stl,obj

# run an agent/user-authored parametric script (generative CAD)
python scripts/generate.py cad --mode script --script mug.py --formats step,stl
```

- **Shapes:** `box` (`--length/--width/--height`), `cylinder` (`--radius/--height`),
  `cone` (`--radius/--radius2/--height`; `radius2 0` = sharp tip), `sphere` (`--radius`),
  `tube` (`--radius/--inner-radius/--height`; bore must be `< radius`).
- **Formats** (`--formats`, default `step,stl`): any subset of **`step`, `stl`, `obj`**.
  `FreeCADCmd` emits **geometry only**; STEP is the BREP/parametric format Blender can't
  read, so `cad` is how you produce it. **glTF is GUI-only in FreeCAD** — export STL and
  hand it to `render --mode mesh` for a Cycles render/turntable, or `render --mode finish`
  for a print-ready figurine. That STL → Blender hop is also the render-for-judge route the
  CAD self-correction loop uses (see `--mode script` below).
- **Binary:** resolved from `--freecad-bin`, `$FREECAD_BIN`, `FreeCADCmd`/`freecadcmd` on
  PATH, then the default Windows install (`C:\Program Files\FreeCAD *\bin\FreeCADCmd.exe`).
- Outputs route to `brands/<brand>/outputs/3d/` (or `outputs/3d/` brandless) with a
  `kind:"cad"` reproducibility sidecar (template, resolved dims/formats, params signature,
  FreeCAD version, pipeline git sha).

### `--mode script` — generative CAD self-correction

`--mode script --script <file.py>` runs an **agent/user-authored FreeCAD Python script** headless and
exports what it builds. The script runs with `App`/`FreeCAD`, `Part`, `Mesh`, and an active `doc` in
scope; it builds geometry as objects in `doc` (or sets `RESULT = [objs]`), and the runner owns
export/emit. STEP export needs **Part (BREP)** objects — a `Mesh::Feature` exports to `stl`/`obj` only
(the runner rejects mesh→STEP with a clear message). The sidecar records the script name + a content
hash, so the `params_signature` varies across in-place revisions.

This is the lever for a **CAD self-correction loop**: a brief → an agent-authored parametric script →
`cad --mode script` → `render --mode mesh` → a VLM judges the form/printability → FIX feedback → the
agent **revises the script** → repeat. When an agent is present it is the script generator (same idea as
the assistant judge backend); an autonomous code-gen backend is roadmap. Live-validated by authoring a
parametric mug, executing it headless, rendering + judging it, then revising the script (roomier handle
+ a BREP rim fillet) and re-running — a real author→exec→render→judge→revise iteration.

> ⚠️ **`--mode script` `exec()`s the script unsandboxed** in the `FreeCADCmd` process (no network,
> isolated process, but full Python — same trust as running a FreeCAD macro you wrote). **Run only
> scripts you authored or audited.** This is a deliberate first-party CLI capability; it is *not* exposed
> as an MCP tool, so the per-tool gates below (which govern the interactive bridge) do not apply to it.
> The gated MCP `execute_code` remains the separate, approval-per-call GUI path.

**Still roadmap:** sketch/constraint modeling, FEM headless, assemblies, and the **autonomous** code-gen
backend for the CAD self-correction loop (the assistant-driven loop above is shipped). Keep a FreeCAD
window open with the addon active for live MCP-assisted editing.

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
