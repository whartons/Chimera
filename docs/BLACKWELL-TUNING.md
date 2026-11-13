# RTX 50-series (Blackwell) ComfyUI tuning guide

A field-tested playbook for getting maximum performance out of an **RTX 50-series
(Blackwell, sm_120)** GPU in ComfyUI — written from an actual RTX 5090 + ComfyUI
**Desktop** setup, with measured results. Most of it applies to any Blackwell card.

> **Headline result (RTX 5090, FLUX.2 dev, 1024×1024, 20 steps, warm):**
> | precision | exec time | notes |
> |---|---|---|
> | fp8 (`flux2_dev_fp8mixed`) | **22.7 s** | baseline |
> | **NVFP4** (`flux2-dev-nvfp4-mixed`) | **8.4 s** | **2.70× faster, no visible quality loss** |
>
> The NVFP4 win **only happens on the cu130 stack below.** On CUDA 12.x, NVFP4
> falls back and runs *slower* than fp8.

---

## 0. Read your startup log first
Open ComfyUI's startup log and look for these lines — they tell you what's
on/off:
- `pytorch version: 2.x.x+cuXXX` — your CUDA build.
- `You need pytorch with cu130 or higher to use optimized CUDA operations` — if
  present, the bundled **comfy-kitchen** FP4/fused kernels are **gated off** (you're
  below cu130). This is the single biggest lever (see step 3).
- `Using pytorch attention` vs `Using sage attention` — your attention backend.
- `comfy_kitchen backend cuda: ... 'disabled': False` — good (FP4 path enabled).

You can also check from the venv:
```bash
<ComfyUI>/.venv/Scripts/python -c "import torch; print(torch.__version__, torch.version.cuda); print('sm_120', 'sm_120' in torch.cuda.get_arch_list())"
```

---

## Levers, lowest-risk first

### 1. `--fast fp16_accumulation` (free, ~15–20% on linear ops)
A CUDA-12-compatible quick win, no install. **Avoid bare `--fast`** — it also turns
on `autotune`, which causes multi-second first-run step hangs. Whitelist just
`fp16_accumulation`. (How to pass launch flags → see [Appendix: ComfyUI Desktop
launch args](#appendix-comfyui-desktop-launch-args).)

### 2. SageAttention 2 + Triton (~25–35% faster sampling)
Biggest low-risk speedup; works on CUDA 12.x too. On Windows use the community
prebuilt wheels (no compiler needed at runtime, but you need the **Visual C++
2015–2022 x64 Redistributable** installed):
```bash
# into the ComfyUI venv:
<ComfyUI>/.venv/Scripts/python -m pip install -U "triton-windows<3.7"   # 3.6.x for torch 2.10 (the reference); 3.4.x for torch 2.8
# SageAttention wheel matched to your torch/CUDA, from:
#   https://github.com/woct0rdho/SageAttention/releases
<ComfyUI>/.venv/Scripts/python -m pip install "<the matching sageattention .whl URL>"
```
Then add the launch flag `--use-sage-attention`. Verify the log flips to
`Using sage attention`. It quantizes attention (approximate) — A/B a couple of
seeds on output-critical work; if a model garbles, drop the flag or use the
per-workflow *Patch Sage Attention* node from ComfyUI-KJNodes instead.

> **Wheel matching matters:** the SageAttention/Triton wheels are tied to your exact
> torch + CUDA. If you later move to cu130 (step 3), reinstall the matching cu130
> wheels (`triton-windows 3.6.x` + a `cu130torch2.9+` SageAttention wheel).

### 3. Move to **cu130** — unlock comfy-kitchen's FP4 CUDA kernels (the big one)
The current ComfyUI build ships optimized FP4/FP8 CUDA kernels (`comfy-kitchen`)
that are **gated behind CUDA 13.0**. A one-line version check disables them on
cu12.x. Moving torch to a `+cu130` build flips the gate and lights up the FP4
tensor-core path on Blackwell.
- **ComfyUI Desktop:** use the app's **Troubleshooting → Reset Environment /
  Reinstall** — the current build's dependency set already targets
  `torch==2.10.0+cu130`. Back up your `.venv` first.
- **Manual (any install), with the app/server stopped:**
  ```bash
  <ComfyUI>/.venv/Scripts/python -m pip install --extra-index-url https://download.pytorch.org/whl/cu130 \
    "torch==2.10.0+cu130" "torchvision==0.25.0+cu130" "torchaudio==2.10.0+cu130"
  ```
- **Verify:**
  ```bash
  <ComfyUI>/.venv/Scripts/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))"
  # expect: 2.10.0+cu130  13.0  <your GPU>
  <ComfyUI>/.venv/Scripts/python -c "from comfy_kitchen.backends.cuda import _CUBLASLT_AVAILABLE; print('cublaslt', _CUBLASLT_AVAILABLE)"
  # expect: cublaslt True   (this is the NVFP4 cuBLASLt GEMM)
  ```
  The startup `need cu130` warning should be **gone**. Your driver must support
  CUDA 13 (recent driver, e.g. 580+).

> **Requires a recent NVIDIA driver.** A bigger torch install also needs disk +
> bandwidth. Keep the `.venv` backup until you've confirmed a few renders.

### 4. NVFP4 model variants (after cu130 — ~2.5–2.7×)
Once cu130 is verified (`_CUBLASLT_AVAILABLE = True`), switch to NVFP4 weights.
For FLUX.2: `black-forest-labs/FLUX.2-dev-NVFP4` →
`flux2-dev-nvfp4-mixed.safetensors` in `models/diffusion_models/`, then point your
workflow's `UNETLoader` at it. Keep the fp8 file as an instant fallback. **Do not**
use NVFP4 on cu12.x — it upcasts and runs slower.

### 5. Distilled / few-step LoRAs (precision-independent, biggest win for video)
Step count dominates generation time. A distilled/Turbo LoRA (e.g. FLUX.2 Turbo,
or the LTX-2 distilled LoRA for video) cuts steps ~20 → ~8 at strength 1.0. Trades
a little fine detail for speed — great for drafts/iteration; re-render keepers at
full steps.

---

## Don't bother (tested dead-ends on Blackwell + Windows)
- ❌ **nunchaku / SVDQuant** for FLUX.2 or LTX-2 — no support (as of 2026); fragile dep, zero benefit.
- ❌ **xformers / FlashAttention-3** — no win over PyTorch SDPA / SageAttention here; FA3 has no reliable sm_120 Windows wheel.
- ❌ **NVFP4 before cu130** — slower than fp8 (upcasts without the FP4 GEMM).
- ❌ **bare `--fast`** — `autotune` causes per-step hangs; whitelist `fp16_accumulation`.
- ❌ Installing Triton expecting it to speed up comfy-kitchen — its CUDA backend already outranks the Triton backend. Install Triton only for SageAttention / `torch.compile`.

---

## The memory guard: a job that won't fit is refused, not run
ComfyUI 0.45 stages a job's model weights in system memory and loads them onto the GPU from there. On Windows a
job whose weights don't fit in the memory left pushes the commit charge past its limit; Windows then grows the page
file and pages until the desktop stops responding. On 2026-11-11 an LTX-2.3 job (36 GB of model files) on the
62 GB reference box, beside an IDE, a browser and another session's test suites, took the commit charge from 87 GB to
122 GB of a 107.6 GB limit: explorer crashed, and the second time ComfyUI had to be stopped from a phone. ComfyUI's
own knobs didn't prevent it: dynamic VRAM filled the card to 30.9 of 31.8 GB with `--reserve-vram 4` set, and
`--cache-ram` only evicts caches.

So Chimera checks every job first (`scripts/brandkit/memguard.py`):
- It finds the model files the job's graph loads through ComfyUI's own model folders (`/internal/folder_paths`)
  and adds up their sizes. A job takes about that much plus 2 GB (measured on the LTX job: 36.1 GB of files, ~35 GB
  of commit growth).
- It compares that with what this machine has left: Windows' commit room (commit limit minus commit charge), or
  `MemAvailable` on Linux, minus 10% of RAM (at least 4 GB) kept for the desktop.
- If the job doesn't fit, it asks ComfyUI to unload models left over from earlier jobs and looks again. If it
  still doesn't fit, `generate.py` stops with the numbers ("render refused: ...") and nothing is queued; the agent
  loops raise the same error.
- Only a ComfyUI on this machine is checked. `CHIMERA_SKIP_MEMORY_CHECK=1` turns the check off.
- `chimera doctor` shows how much memory jobs can take right now, and warns under 8 GB.

What jobs need on the reference box (model files + 2 GB):

| Job | Needs |
|---|---|
| Z-Image | ~14 GB |
| Qwen-Image-2.1, including `relight --model qwen_image…` | ~18 GB |
| Stable Audio 3 | ~16 GB |
| ACE-Step | ~21 GB |
| foley | ~8 GB |
| TRELLIS.2 | ~16 GB |
| Wan 2.2 | ~37 GB (+5 GB with RelayVSR `--upscale`) |
| LTX-2.3 | ~38 GB |
| FLUX.2 nvfp4, the default relight | ~40 GB |
| FLUX.2 fp8 | ~52 GB |

The FLUX.2 figures assume the fp8 text encoder, which every FLUX.2 graph has loaded since 2026-11-12; with the
bf16 encoder FLUX.2 needed ~68 GB. On a 62 GB machine, FLUX.2 and the video models need the machine mostly to
themselves.

ComfyUI keeps the last job's models cached, and the guard can't tell which models those are. So a job that only
fits after an unload gets one first, even when it's the same models, and a back-to-back repeat of a big job
reloads them (about 10–20 s for FLUX.2).

`--cache-ram <GB>` is still worth setting: ComfyUI evicts its caches and stops pinning more memory while less than
that is free (its default is 10% of RAM, at most 10 GB). The reference box runs `--cache-ram 15.5`. `--reserve-vram`
does nothing under dynamic VRAM, so it isn't set.

---

## Appendix: ComfyUI Desktop launch args
ComfyUI **Desktop** has **no GUI field** for arbitrary server flags (and its
`config.json` `extraArgs` key is ignored — a common wrong guess). The real
mechanism is the frontend setting **`Comfy.Server.LaunchArgs`** in:
```
%APPDATA%\ComfyUI\... \user\default\comfy.settings.json     (Windows)
```
It's an **object** mapping arg-name → value; an empty value emits a bare flag:
```json
"Comfy.Server.LaunchArgs": {
  "fast": "fp16_accumulation",
  "use-sage-attention": "",
  "output-directory": "D:/wherever/you/want/outputs"
}
```
→ serializes to `--fast fp16_accumulation --use-sage-attention --output-directory D:/...`.
**Edit it only while the app is fully closed** (it rewrites the file on exit and
will clobber live edits), then reopen. A manual `python main.py` install just takes
these as normal CLI flags.

**Comfy Desktop 1.1.x** also keeps a per-installation launch line, `launchArgs` in
`%APPDATA%\Comfy Desktop\installations.json` (for example
`"--port 8000 --fast fp16_accumulation --use-sage-attention --enable-manager --cache-ram 15.5"`), and that line is
what the server starts with: flags appended there were live on the next start (2026-11-11). Quit the app from its
tray icon before editing it, too.

> Bonus: `output-directory` is how you point renders at any folder (e.g. a synced
> drive) without moving your models.
