# `blender` module — requirements

This module is a **DCC bridge**, not a ComfyUI modality. There are no ML model
weights to download and no `ComfyUI/models/` destination. Requirements are an
application, an MCP server, and a Blender addon — all listed below.

---

## Application

| | |
|---|---|
| **App** | Blender |
| **Minimum version** | **5.1.0** |
| **Install** | Per your OS — see [`../../docs/SETUP.md`](../../docs/SETUP.md) |
| **Required setting** | **Online access enabled** (`Edit → Preferences → System → Network → Allow Online Access`) — the addon will not connect without it |

Download from [blender.org](https://www.blender.org/download/). No Blender-side
Python packages need to be installed separately; the addon ships its own dependencies.

---

## MCP server + addon

| | |
|---|---|
| **Server** | `lab/blender_mcp` |
| **Source** | Gitea — `projects.blender.org/lab/blender_mcp` |
| **Pinned ref** | commit `98b0e49d98321d321c7e631389200f513f765d59` (`v1.0.0` +1, docs-only) |
| **License** | GPL-3.0-or-later |
| **Python deps** | `docutils`, `mcp[cli]`, `pyyaml` — fetched automatically by `uv` |
| **Launcher** | `uvx --from "git+https://projects.blender.org/lab/blender_mcp@98b0e49d98321d321c7e631389200f513f765d59#subdirectory=mcp" blender-mcp` (server package is in the repo's `mcp/` subdir) |
| **Console script** | `blender-mcp` (module: `blmcp`) |
| **Addon path** | `addon/blender_mcp_addon/` inside the pinned repo |
| **Addon destination** | Blender's add-ons/extensions directory (installed via `Edit → Preferences → Add-ons → Install from Disk`) |
| **Socket** | Loopback TCP `127.0.0.1:9876` — auto-starts when the addon is enabled |

The MCP server entry is registered in [`../../.mcp.json`](../../.mcp.json) at
project scope. Do not install from PyPI with the bare `uvx blender-mcp` — that PyPI name
is a different, rejected server; always launch from the pinned Gitea ref with
`#subdirectory=mcp` (the server package is in the repo's `mcp/` subdir).

---

## Headless render

The `generate.py render` backend (`--mode mesh` / `comfy-scene` / `finish`) calls
`blender --background --python <template>` as a subprocess. Additional requirements
beyond those above:

| | |
|---|---|
| **`blender` on PATH** | or set `$BLENDER_BIN` — the runner picks up `$BLENDER_BIN` first, then falls back to `blender` on `PATH` |
| **Minimum version** | **5.1.0** (same as interactive; templates are validated against 5.1) |
| **Render engine** | **Cycles** (CUDA or OptiX) — GPU render. **EEVEE is not suitable for headless use** outside Linux (EGL required); on Windows and macOS, Cycles is the only viable headless engine. This does not affect the interactive bridge, which uses whatever engine is active in the running scene |
| **MP4 turntable** (`--turntable`) | uses Blender's **bundled FFmpeg** — no separate FFmpeg install. Set via `image_settings.media_type='VIDEO'` in the 5.x bpy API |

This does not affect the interactive MCP bridge (which renders inside the running
Blender GUI) and has no additional Python package requirements.

---

## No ComfyUI model weights

This module does not route through a ComfyUI graph and has no diffusion, VAE, CLIP,
or other ML checkpoints. There is **no `ComfyUI/models/` destination** and nothing to
download from Hugging Face or Civitai. All compute runs inside the Blender process
(or the `blender --background` subprocess in Phase 2).
