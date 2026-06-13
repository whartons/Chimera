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
| **Pinned ref** | commit `03004fd0216bfe5e0a3d9ac9b47d5efadc3d78c4` (`v1.0.0`) |
| **License** | GPL-3.0-or-later |
| **Python deps** | `docutils`, `mcp[cli]`, `pyyaml` — fetched automatically by `uv` |
| **Launcher** | `uv run --from git+https://projects.blender.org/lab/blender_mcp@03004fd0216bfe5e0a3d9ac9b47d5efadc3d78c4 blender-mcp` |
| **Console script** | `blender-mcp` (module: `blmcp`) |
| **Addon path** | `addon/blender_mcp_addon/` inside the pinned repo |
| **Addon destination** | Blender's add-ons/extensions directory (installed via `Edit → Preferences → Add-ons → Install from Disk`) |
| **Socket** | Loopback TCP `127.0.0.1:9876` — auto-starts when the addon is enabled |

The MCP server entry is registered in [`../../.mcp.json`](../../.mcp.json) at
project scope. Do not install from PyPI (`uvx blender-mcp`) — the PyPI package under
that name is a different, rejected server; always launch from the pinned Gitea ref.

---

## Render engine note (Phase 2)

Headless renders — `blender --background --python` driven by the self-correction loop
(Phase 2+) — use **Cycles with CUDA or OptiX** for GPU acceleration. **EEVEE is not
suitable for headless use** outside Linux (EGL support required); on Windows and macOS,
Cycles is the only viable headless render engine. This does not affect the interactive
MCP bridge (Phase 1), which renders inside the running Blender GUI using whatever
engine is active in the scene.

---

## No ComfyUI model weights

This module does not route through a ComfyUI graph and has no diffusion, VAE, CLIP,
or other ML checkpoints. There is **no `ComfyUI/models/` destination** and nothing to
download from Hugging Face or Civitai. All compute runs inside the Blender process
(or the `blender --background` subprocess in Phase 2).
