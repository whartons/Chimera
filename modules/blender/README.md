# `blender` — image-and-scene DCC bridge

![A 360-degree headless Cycles turntable of a generated mesh](../../docs/images/chimera-sample-blender.gif)

*Headless Cycles turntable of a generated mesh — `chimera render --from mesh.glb --turntable`. Brand-neutral sample.*

This module covers **two shipped paths** for driving Blender from Chimera:

1. **Interactive MCP bridge** — an AI assistant connects to a running Blender GUI
   session over a loopback socket, introspects the scene graph, manipulates objects,
   executes Python operations, and fires renders into a folder you choose.
2. **Headless render backend** — `generate.py render` shells to `blender --background`
   with parameterized `bpy` templates; no GUI required, no per-call MCP approval.
   Three modes, all live-validated on Blender 5.1 / RTX 5090 — see below.

Phase 3 — a VLM self-correction loop that judges its own renders — is **shipped**
(`auto_generate.py --pipeline mesh3d`; the `mesh_eval.py` template + the `agent` module power it).
See [`../agent/self-correction.md`](../agent/self-correction.md).

## The MCP bridge

| | |
|---|---|
| **Server** | official `lab/blender_mcp` (Blender Foundation) — Gitea `projects.blender.org` |
| **Pinned** | commit `98b0e49d98321d321c7e631389200f513f765d59` (v1.0.0 +1, docs-only) |
| **License** | GPL-3.0-or-later · runs 100% locally (loopback `127.0.0.1:9876`) |
| **Transport** | stdio (Claude launches it) → TCP socket → Blender addon |
| **Tools** | 26: scene introspection, object ops, code-exec, render, screenshots, doc search |

> **Why `lab/blender_mcp` and not `ahujasid/blender-mcp`?** The Blender Foundation
> server is first-party, carries zero telemetry (deps are exactly `docutils`,
> `mcp[cli]`, and `pyyaml`), and is headless-capable. The high-profile community fork
> is GUI-only, ships opt-out Supabase telemetry with a bloated dependency chain, and
> had a live arbitrary-file-read bug in the wild — none of that is acceptable for a
> public, security-audited pipeline.

## Activate it

Prerequisites: **[Astral `uv`](https://docs.astral.sh/uv/)** installed and on your
`PATH`; **Blender ≥ 5.1.0** with **online access enabled** (`Edit → Preferences →
System → Network → Allow Online Access`).

1. **Install the Blender addon.** Clone (or download) `lab/blender_mcp` at the pinned
   commit `98b0e49d98321d321c7e631389200f513f765d59`. Install `addon/blender_mcp_addon/` via
   `Edit → Preferences → Add-ons → Install from Disk`. Enable it. The addon
   auto-starts the loopback socket (`127.0.0.1:9876`) on enable — no extra step needed.

2. **Register the MCP server.** The server entry lives in
   [`../../.mcp.json`](../../.mcp.json) and is launched by Claude Code as:
   ```
   uvx --from "git+https://projects.blender.org/lab/blender_mcp@98b0e49d98321d321c7e631389200f513f765d59#subdirectory=mcp" blender-mcp
   ```
   The `#subdirectory=mcp` is required — the server package lives in the repo's `mcp/`
   subdir (the root has no installable package). Never use the **bare** `uvx blender-mcp`:
   that PyPI name resolves to a **different, rejected server** (see security notes below).

3. **Approve and confirm.** In Claude Code run **`/mcp`**, approve the `blender` server
   (project-scoped servers require a one-time approval). Confirm: `/mcp` should show
   `blender` **Connected** with 26 tools. Ask the assistant to call
   `get_objects_summary` — it should return the active Blender scene's objects, proving
   the bridge reached the addon.

## Two execution paths

### Interactive MCP bridge (GUI)

The MCP bridge requires Blender's **GUI to be running** and the addon enabled. Keep a
Blender window open and the addon active for any MCP-assisted work. Every call to
`execute_blender_code*` requires per-call approval (Tier 1); render and path tools
require approval + a path allowlist (Tier 2).

### Headless render backend (`generate.py render`)

The headless path runs entirely as a **normal CLI subprocess** — `blender --background
--python <template>` — with no Blender GUI and no per-call MCP approval. Templates
live in `workflows/templates/blender/` and are parameterized at call time. The runner
lives in `scripts/brandkit/blender.py`; invoke it via:

```bash
generate.py render [--brand <brand>] --from <file> [--mode <mode>] [options]
```

Three modes, all live-validated on Blender 5.1 / RTX 5090:

- **`--mode mesh`** *(default)* — import a mesh (GLB / STL / OBJ) → studio look → Cycles
  → hero PNG. Add `--turntable` to also produce an MP4 orbit animation.
- **`--mode comfy-scene`** — take a ComfyUI image → emissive backdrop + reflective floor
  + focal object → Cycles render. This is the **ComfyUI → Blender handoff**: a
  ComfyUI-generated image becomes a scene element in a lit Blender set.
- **`--mode finish`** — AI mesh → clean → optional `--watertight` voxel remesh →
  decimate (`--target-tris`) → optional `--scale-mm` → material (or `--color project`)
  → export STL / GLB (+ hero render). The **figurine / character-finish** pipeline for
  print-ready output.

All modes are **brand-aware**: outputs route to `brands/<brand>/outputs/` (or `outputs/`
when brandless) with a `kind:"render"` sidecar. The test suite mocks the subprocess,
so CI stays GPU-free.

A fourth template, **`mesh_eval.py`**, powers the Phase 3 3D self-correction loop rather than the
`render` CLI: it imports a mesh → renders **4 orbit stills** (Cycles) → computes **bmesh geometry
checks** (non-manifold / open-edge / loose-part / tri-count / bounds) → emits both in its manifest. The
agent loop montages the stills into one contact sheet for the VLM judge and folds the geometry checks
into the verdict (see [`../agent/self-correction.md`](../agent/self-correction.md) §3D self-correction).

**Phase 4a — albedo texturing.** With `texture: true` + a concept `asset`, `mesh_eval` calls
`_common.bake_albedo()`, which `smart_project`-unwraps the mesh, projects the concept from a dead-front
camera (via `world_to_camera_view` — `bpy.ops.uv.project_from_view` is unusable under `--background`),
shader-masks front faces vs a flat `back_fill` (`palette` color, or a `mirror` back-projection), and
EMIT-bakes a `texture_res` albedo atlas; `mesh_eval` then exports a self-contained **textured GLB** and
emits `textured`/`textured_glb`. The stills come out colored. Driven by `--pipeline mesh3d --texture`.

**Phase 4b — all-around multi-view bake.** Phase 4a colors a mesh from one front projection (faithful
front, flat back). `generate.py finalize-texture --from <glb> --views front,right,back,left` finalizes a
**winning** mesh once with real all-around color: the **`mesh_finalize.py`** template calls
**`_common.bake_multiview()`**, which generalizes `bake_albedo` from 1 → N views — a ring camera per view,
a per-view `world_to_camera_view` projection UV, a per-view front-facing weight `max(0,dot(N,-dir))²`, a
weighted blend `Σ(w·c)/max(Σw,ε)`, and a flat `--back-fill` (`palette`/`grey`) for faces no view sees —
then EMIT-bakes the atlas, exports a textured GLB, and renders orbit verification stills. The corrected
views can be **supplied** (`--views`, an artist's paints) **or auto-generated** (`--auto-repaint --concept
<img> --subject "..."`): `render_views.py` renders a per-view depth map, then an SDXL
**depth-ControlNet + IPAdapter** repaint (`scripts/brandkit/repaint.py`) generates each view from the
concept. Runs through the same headless job runner; routes the GLB + a contact sheet to `outputs/` with a
`kind:"render" mode:"finalize-texture"` sidecar.

Phase 3 (self-correction over renders), Phase 4a (front albedo texturing), and Phase 4b (the multi-view
**bake** + **auto-repaint**) are all **shipped** (`auto_generate.py --pipeline mesh3d [--texture|--finalize]`;
`generate.py finalize-texture [--auto-repaint]`); see [`../agent/self-correction.md`](../agent/self-correction.md).
`--finalize` is the in-loop driver: it auto-runs this `finalize-texture --auto-repaint` bake on the
self-correction loop's winning mesh and re-judges the textured result.

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
- **Pin from commit, never the bare `uvx blender-mcp`.** The PyPI package `blender-mcp` is a
  different server that was rejected during audit. Always launch from the pinned
  `projects.blender.org` git ref with `#subdirectory=mcp`.
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
