# Setup

## ComfyUI install
Use the official ComfyUI **Desktop** app or a manual git install. **RTX 50-series
(Blackwell, incl. the 5090) needs CUDA 12.8+ to run at all.** The current ComfyUI
Desktop build also ships bundled optimized kernels (`comfy-kitchen`) that are gated
behind **CUDA 13.0 (cu130)** — a standard CUDA 12.x build drives a 5090 correctly but
leaves the FP4 tensor-core path disabled (you'll see a `You need pytorch with cu130 or
higher` warning at startup). See [Performance tuning](#performance-tuning-rtx-50-series--blackwell).

**Version:** Chimera's default models run on **core nodes from ComfyUI 0.40**: Qwen-Image-2.1, the SeedVR2
upscaler, Wan 2.2 (incl. Fun Camera), Stable Audio 3, and TRELLIS.2 / Pixal3D. On an older build (≥ 0.24),
pass `--model` to use the earlier models (Z-Image / FLUX.2, LTX-2.3, ACE-Step, Hunyuan3D 2.1). There, image
`--upscale` also needs `--upscale-model 4x-UltraSharp.pth` (SeedVR2's nodes are new in 0.40),
`audio --mode sfx` has no older path (it is Stable Audio 3 only), and the mesh3d agent loop needs
`--mesh-model hunyuan21`, plus `--model` with a Z-Image or FLUX.2 file for its concept image (or
`--from-image`). On 0.40, LTX-2.3 needs the bundled LTXVideo patch (see
[`../modules/video/README.md`](../modules/video/README.md)).

## This repo
```bash
git clone <your-fork-url> chimera
cd chimera
cp .env.example .env        # fill in any API keys (gitignored)
mkdir -p workflows/personal outputs
```

Chimera doesn't load `.env` itself: export the variables you need in your shell before you run the CLI or
the agent loop.

## Per-module models
Each `modules/<name>/models.md` lists the model files, their Hugging Face /
Civitai URLs, target paths under `ComfyUI/models/...`, and license. Download what
a module needs before importing its default graph: `modules/image/workflow.qwen-image-txt2img.template.json`,
`modules/video/workflow.wan22-i2v.template.json`, `modules/audio/workflow.sa3.template.json`, or
`modules/threed/workflow.trellis2.template.json`. (A module's plain `workflow.template.json` is an earlier
model's graph: FLUX.2, LTX-2.3, or Hunyuan3D 2.1.)

The **defaults** come from ungated Comfy-Org repos (no Hugging Face login): about 119 GB in all, or about
88 GB without the camera-move models. These sizes are decimal GB, as Hugging Face lists them; Windows (and
[`CATALOG.md`](CATALOG.md)'s per-file sizes) show about 7% less.

| Modality | Default | Download |
|---|---|---|
| image | Qwen-Image-2.1 | ~17 GB |
| `--upscale` | SeedVR2 7B | ~9 GB |
| video | Wan 2.2 | ~38 GB (+ ~31 GB for `--camera` moves) |
| music / sfx | Stable Audio 3 | ~15 GB |
| 3D | TRELLIS.2 | ~9 GB (+ ~6 GB for `--model pixal3d`) |

Skip any modality you don't use: each module's `models.md` lists its exact files, and `chimera doctor` reports,
per modality, which default model files ComfyUI can't see. If ComfyUI rejects a job anyway (a model file it
doesn't have, a value out of range), the CLI prints its validation error on one line with a `chimera doctor`
hint. Comfy-Org's "repackaged" repos nest files under `split_files/<type>/`: place them in `models/<type>/`,
without the `split_files` level.

## VRAM
Baseline dev hardware: RTX 5090, 32 GB, and the defaults aim high. The README's
[Hardware table](../README.md#%EF%B8%8F-hardware) lists each default's GPU memory and the route for a
smaller card; each module README's VRAM notes have the details. Chimera's graphs load the fp8 / int8 /
NVFP4 files each `models.md` names; GGUF quants need ComfyUI-GGUF's own loader nodes, so they suit your own
workflows rather than Chimera's graphs.

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
5. **Distilled / few-step LoRAs** (e.g. Wan 2.2's lightx2v 4-step LoRAs, Chimera's default `--quality fast`,
   or the LTX-2 distilled LoRA). Cutting the step count beats any kernel change for video, and needs no install.

Don't bother on Blackwell + Windows: **nunchaku** (no FLUX.2/LTX-2 support as of 2026),
**xformers / FlashAttention-3** (no win over SDPA/SageAttention here), or **NVFP4 before
cu130** (slower).

## MCP / agent layer
The `modules/agent/` layer drives ComfyUI through an existing MCP server — see
[../modules/agent/README.md](../modules/agent/README.md). Point it at your running
instance: ComfyUI **Desktop defaults to `127.0.0.1:8000`**; a manual `python main.py`
install uses `8188`.

### Local models for the self-correction loops
`scripts/agent/auto_generate.py` judges, rewrites prompts and writes CAD scripts with local
[Ollama](https://ollama.com) models picked by your GPU's memory (`--llm-tier` or `CHIMERA_LLM_TIER` to choose).
Pull your tier's models; `chimera doctor` shows the tier it picked and the `ollama pull` command for any
model that's missing.

| GPU memory | Tier | Pull |
|---|---|---|
| 32 GB+ | large | `qwen3.8:27b` |
| 12–24 GB | medium | `qwen3-vl:8b-instruct`, plus `qwen3.8:27b` for `--pipeline cad` |
| under 12 GB | small | `qwen3-vl:4b-instruct`, plus `qwen3.8:27b` for `--pipeline cad` (mostly on the CPU, slow) |

Any role can use a hosted OpenAI-compatible API instead: see [`.env.example`](../.env.example) and
[Local models by GPU tier](../modules/agent/self-correction.md#local-models-by-gpu-tier).

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
   `4309a396`) as a Blender extension and enable it. The socket **auto-starts on enable**
   (`127.0.0.1:9876`).
3. The server is launched by Claude via `.mcp.json`
   (`uvx --from "git+…@<sha>#subdirectory=mcp" blender-mcp` — the server package is in the repo's
   `mcp/` subdir) — **never** the bare `uvx blender-mcp` (a different PyPI package) and **never**
   pass `-t http`.
4. In Claude Code: `/mcp` → approve **blender** (project-scoped servers need one-time approval).

### FreeCAD
1. Install **FreeCAD 1.1.4 or newer** (winget `FreeCAD.FreeCAD` or freecad.org; earlier releases
   have HIGH security advisories triggered by opening a crafted `.FCStd`).
2. Copy the **whole `FreeCADMCP` addon** directory (`addon/FreeCADMCP/` at commit `78bf023`,
   including its `package.xml`) into FreeCAD's user `Mod/` dir, keeping no backup copies inside `Mod/`. **FreeCAD 1.1 uses a versioned data dir** — Windows: `%APPDATA%\FreeCAD\v1-1\Mod\`
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
