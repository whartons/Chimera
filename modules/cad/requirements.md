# `cad` module — requirements

> **DCC/CAD bridge, not a ComfyUI modality.** This module bridges FreeCAD over
> MCP — it has no `ComfyUI/models/` destination, no ML weights to download, and
> no ComfyUI graph. Nothing here goes into your ComfyUI install.

---

## Application

| | |
|---|---|
| **App** | FreeCAD **1.0 or 1.1** |
| **Python** | 3.12 (bundled with FreeCAD 1.0+) |
| **Download** | <https://www.freecad.org/downloads.php> |

FreeCAD must be running with its GUI active for MCP-assisted work (see [README.md](README.md)).

---

## MCP server

| | |
|---|---|
| **Package** | `neka-nat/freecad-mcp` |
| **Pinned commit** | `63acb30` (= published release `0.1.18`) |
| **Source** | <https://github.com/neka-nat/freecad-mcp> |
| **License** | MIT |
| **Console script** | `freecad-mcp` → `freecad_mcp.server:main` |
| **Runtime deps** | `mcp[cli]`, `validators` |
| **Launcher** | `uvx --from git+https://github.com/neka-nat/freecad-mcp@63acb30 freecad-mcp --host 127.0.0.1` |

The server is launched via [`../../.mcp.json`](../../.mcp.json) using Astral's `uv`
(`uvx`) so no manual install step is needed — `uv` resolves the pinned git ref on
first use.

### FreeCAD addon

The repo ships a companion addon at `addon/FreeCADMCP/` (same commit `63acb30`).

| | |
|---|---|
| **Addon directory** | `addon/FreeCADMCP/` (in the server repo at the pinned commit) |
| **Destination (Windows)** | `%APPDATA%\FreeCAD\Mod\FreeCADMCP\` |
| **Destination (macOS)** | `~/Library/Preferences/FreeCAD/Mod/FreeCADMCP/` |
| **Destination (Linux)** | `~/.local/share/FreeCAD/Mod/FreeCADMCP/` |
| **Transport** | loopback XML-RPC on `127.0.0.1:9875` |
| **Start** | Select **"MCP Addon" workbench** → click **"Start RPC Server"** toolbar button |
| **Auto-start** | opt-in, **default OFF** — server is only exposed on explicit user action |

After copying the addon directory into `Mod/`, restart FreeCAD before enabling the
workbench.

---

## Headless automation (Phase 2+)

The interactive MCP bridge requires a live FreeCAD GUI window. For the
unattended self-correction loop, the Phase 2 automation path will shell out to
`FreeCADCmd` — for example:

```
C:\Program Files\FreeCAD 1.0\bin\FreeCADCmd.exe  script.py
```

`FreeCADCmd` emits **geometry only** (STEP / STL / glTF — no headless renderer).
Rendering for the judge step goes through the Blender Cycles step in the pipeline.
This path does not exist yet; it is documented here as a forward reference.

---

## No models to download

This module has no ML weights, no diffusion checkpoints, and no Hugging Face
dependencies. The only artifacts to acquire are:

1. FreeCAD 1.0 or 1.1 (from <https://www.freecad.org/downloads.php>).
2. The `addon/FreeCADMCP/` directory from the pinned commit `63acb30` (copy to
   your FreeCAD `Mod/` directory as described above).

`uv` / `uvx` handles the Python server package automatically at launch time from
the pinned git ref — no manual `pip install` required.
