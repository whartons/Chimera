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
<ComfyUI>/.venv/Scripts/python -m pip install -U "triton-windows<3.5"   # match your torch (3.6.x for torch 2.10)
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

> Bonus: `output-directory` is how you point renders at any folder (e.g. a synced
> drive) without moving your models.
