# Image module — models

FLUX.2 [dev] is a **split** model: a diffusion transformer + a separate text
encoder + a separate VAE (it is *not* an all-in-one checkpoint, so it loads via
`UNETLoader` / `CLIPLoader` / `VAELoader`, not `CheckpointLoaderSimple`).

Download these from the Comfy-Org / Black Forest Labs Hugging Face repos and drop
each into the matching `ComfyUI/models/...` folder. Filenames must match the ones
in [`workflow.template.json`](workflow.template.json) (or edit the template to
match what you downloaded).

| File | Goes in | Source | License |
|------|---------|--------|---------|
| `flux2_dev_fp8mixed.safetensors` | `models/diffusion_models/` | Comfy-Org FLUX.2 repackage (Hugging Face) | FLUX.2 [dev] non-commercial — fine for personal use |
| `mistral_3_small_flux2_bf16.safetensors` | `models/text_encoders/` | Comfy-Org FLUX.2 text encoders (Hugging Face) | Mistral / Apache-2.0 |
| `flux2-vae.safetensors` | `models/vae/` | Comfy-Org FLUX.2 repo (Hugging Face) | FLUX.2 [dev] |

> Find them via the ComfyUI **Templates Library** (it links the exact downloads),
> or **ComfyUI-Manager → Model Manager**, or search Hugging Face for
> `Comfy-Org FLUX.2`.

## Faster / lighter variants (optional)
- **NVFP4 (RTX 50-series / Blackwell only):**
  `flux2-dev-nvfp4-mixed.safetensors` from
  [`black-forest-labs/FLUX.2-dev-NVFP4`](https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4)
  → `models/diffusion_models/`. Measured **~2.7× faster** than fp8 at equal
  quality on an RTX 5090 — **requires the cu130 stack** (see
  [`../../docs/BLACKWELL-TUNING.md`](../../docs/BLACKWELL-TUNING.md)). On CUDA 12.x
  it falls back and runs *slower* than fp8, so only use it after cu130.
  To use it, set `unet_name` in the workflow to this file.
- **Turbo LoRA** (few-step): a FLUX.2 Turbo LoRA in `models/loras/` lets you drop
  `steps` to ~8 (add a `LoraLoaderModelOnly` node before the sampler). Trades a
  little fine detail for speed — good for drafts.

## VRAM
- fp8 (`flux2_dev_fp8mixed`): runs in ~16–24 GB; ~12 GB load footprint observed.
- NVFP4: smaller footprint, faster, **cu130 only**.
- Tight on VRAM? Use GGUF/quantized variants via `ComfyUI-GGUF`, or smaller
  resolutions.
