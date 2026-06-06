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

1. **`--fast fp16_accumulation`** — free, ~15–20% on linear ops. ComfyUI Desktop has
   no GUI args field; add launch flags to `%APPDATA%\ComfyUI\config.json` as an
   `extraArgs` array, each token a separate element:
   `"extraArgs": ["--fast", "fp16_accumulation"]`. Avoid bare `--fast` — its
   `autotune` causes multi-second first-run step hangs.
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
