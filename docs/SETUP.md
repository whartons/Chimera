# Setup

## ComfyUI install
Use the official ComfyUI **Desktop** app or a manual git install. **RTX 50-series
(Blackwell, incl. the 5090) needs CUDA 12.8+ to run at all.** The current ComfyUI
Desktop build also ships bundled optimized kernels (`comfy-kitchen`) that are gated
behind **CUDA 13.0 (cu130)** — a standard CUDA 12.x build drives a 5090 correctly but
leaves the FP4 tensor-core path disabled (you'll see a `You need pytorch with cu130 or
higher` warning at startup). See [Performance tuning](#performance-tuning-rtx-50-series--blackwell).

## This repo
```bash
git clone <your-fork-url> chimera
cd chimera
cp .env.example .env        # fill in any API keys (gitignored)
mkdir -p workflows/personal outputs
```

## Per-module models
Each `modules/<name>/models.md` lists the model files, their Hugging Face /
Civitai URLs, target paths under `ComfyUI/models/...`, and license. Download what
a module needs before importing its `workflow.template.json`.

## VRAM
Baseline dev hardware: RTX 5090, 32 GB. Most modules run on 8–16 GB via
quantized weights — see each module's notes. Install `ComfyUI-GGUF` for quantized
loading and use NVFP4 / fp8 variants where available for speed on RTX.

## Performance tuning (RTX 50-series / Blackwell)
Check your current state in the ComfyUI **startup log**: the attention backend line
(`Using pytorch attention` vs `Using sage attention`) and whether the
`You need pytorch with cu130 or higher` warning is present (that warning means the
optimized FP4/FP8 CUDA kernels are gated off). Levers, lowest-risk first:

1. **`--fast fp16_accumulation`** — free, ~15–20% on linear ops. ComfyUI Desktop has no
   GUI args field; the supported way to pass launch flags is the frontend setting
   **`Comfy.Server.LaunchArgs`** (Settings → search "LaunchArgs"). The `config.json`
   `extraArgs` key is **ignored** — see the [Blackwell tuning guide](BLACKWELL-TUNING.md)
   for the exact mechanism and value format. Avoid bare `--fast` — its `autotune` causes
   multi-second first-run step hangs.
2. **SageAttention 2 + Triton** — ~25–35% faster sampling; the biggest low-risk win.
   On Windows use the community prebuilt wheels: `triton-windows` (matched to your
   torch version) and a SageAttention wheel from the woct0rdho releases; enable with
   the `--use-sage-attention` launch flag. It quantizes attention (approximate) — A/B
   a few seeds on output-critical work. Needs the *Visual C++ 2015–2022 x64
   Redistributable*.
3. **Move to cu130** to unlock `comfy-kitchen`'s fused FP4/FP8 CUDA kernels. The
   Desktop's own dependency set already targets `torch==2.10.0+cu130`; the supported
   path is the app's **Troubleshooting → Reset Environment / Reinstall**. Back up your
   `.venv` first. Verify `torch.version.cuda == "13.0"` and that the cu130 warning is gone.
4. **NVFP4 model variants** (e.g. `FLUX.2-dev-NVFP4`) — ~2.5× speed / less VRAM, but
   **only after cu130** (on CUDA 12.x they upcast and run *slower*). Keep an fp8 copy
   as an instant fallback.
5. **Distilled / few-step LoRAs** (e.g. the LTX-2 distilled LoRA) — cutting step count
   beats any kernel change for video, and needs no install.

Don't bother on Blackwell + Windows: **nunchaku** (no FLUX.2/LTX-2 support as of 2026),
**xformers / FlashAttention-3** (no win over SDPA/SageAttention here), or **NVFP4 before
cu130** (slower).

## MCP / agent layer
The `modules/agent/` layer drives ComfyUI through an existing MCP server — see
[../modules/agent/README.md](../modules/agent/README.md). Point it at your running
instance: ComfyUI **Desktop defaults to `127.0.0.1:8000`**; a manual `python main.py`
install uses `8188`.

## DCC / CAD bridges (Blender + FreeCAD)
These add an assistant-driven bridge to a **live** Blender and FreeCAD (interactive, Phase 1). Both run
100% locally over a loopback socket. **Headless automation also ships** — `generate.py render` (Blender)
and `generate.py cad` (FreeCAD), plus the `auto_generate.py --pipeline mesh3d` / `--pipeline cad`
self-correction loops. Full details:
[../modules/blender/README.md](../modules/blender/README.md) · [../modules/cad/README.md](../modules/cad/README.md).

### Prerequisite: `uv`
The Python MCP servers launch via Astral's `uv`. Install once:
`winget install astral-sh.uv` (or see https://docs.astral.sh/uv/). Confirm: `uv --version`.

### Blender
1. Install **Blender ≥ 5.1.0** (winget `BlenderFoundation.Blender` or blender.org) and enable
   **online access** (Edit → Preferences → System) — the addon requires it.
2. Install the **`lab/blender_mcp` addon** (`addon/blender_mcp_addon/` from the pinned commit
   `03004fd`) as a Blender extension and enable it. The socket **auto-starts on enable**
   (`127.0.0.1:9876`).
3. The server is launched by Claude via `.mcp.json`
   (`uvx --from "git+…@<sha>#subdirectory=mcp" blender-mcp` — the server package is in the repo's
   `mcp/` subdir) — **never** the bare `uvx blender-mcp` (a different PyPI package) and **never**
   pass `-t http`.
4. In Claude Code: `/mcp` → approve **blender** (project-scoped servers need one-time approval).

### FreeCAD
1. Install **FreeCAD 1.0 or 1.1** (winget `FreeCAD.FreeCAD` or freecad.org).
2. Copy the **`FreeCADMCP` addon** (`addon/FreeCADMCP/` at commit `63acb30`) into FreeCAD's user
   `Mod/` dir. **FreeCAD 1.1 uses a versioned data dir** — Windows: `%APPDATA%\FreeCAD\v1-1\Mod\`
   (1.0 omits the `v1-1`). Unsure? In FreeCAD use **Tools → Open user data directory** and copy into
   the `Mod/` there. Then **fully restart FreeCAD** and select the **"MCP Addon" workbench**.
3. Click the **"Start RPC Server"** toolbar button (auto-start is opt-in, default OFF) → binds
   `127.0.0.1:9875`. **Leave "Remote Connections" OFF.**
4. In Claude Code: `/mcp` → approve **freecad**.

### Verify
`/mcp` shows **blender** and **freecad** Connected with a non-empty tool list. Ask the assistant
to call one read-only tool on each (Blender `get_objects_summary`, FreeCAD `get_objects`).

> **Security:** never open untrusted `.blend` files in an MCP session. The dangerous (code-exec)
> tools require per-call approval — see each module's README.
