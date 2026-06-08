# Image module — models

Two backends are supported. **Z-Image is the default**; FLUX.2 is secondary and
can be activated by passing a `flux2*` model name.

Download the files for your chosen backend from Hugging Face and drop each into
the matching `ComfyUI/models/...` folder. Filenames must match the ones in the
relevant template (or edit the template to match what you downloaded).

---

## Z-Image (default)

Tongyi Z-Image — core-native in ComfyUI 0.22.3, no custom node pack required.
Uses a **Qwen-3-4B text encoder** and the AuraFlow sampler schedule.

HuggingFace repo: `Comfy-Org/z_image_turbo` (both the turbo nvfp4 and the base
bf16 weights are published there alongside the shared encoder and VAE).

| File | Destination (`ComfyUI/models/…`) | Size | License |
|------|----------------------------------|------|---------|
| `z_image_turbo_nvfp4.safetensors` | `diffusion_models/` | ~4.5 GB | ✅ Apache-2.0 |
| `z_image_bf16.safetensors` | `diffusion_models/` | ~12.3 GB | ✅ Apache-2.0 |
| `qwen_3_4b.safetensors` *(shared)* | `text_encoders/` | ~8 GB | ✅ Apache-2.0 |
| `ae.safetensors` *(shared)* | `vae/` | ~0.3 GB | ✅ Apache-2.0 |

> The `Comfy-Org/z_image_turbo` repo hosts both the turbo model and the shared
> encoder + VAE. Find them via the ComfyUI **Templates Library** (sidebar),
> **ComfyUI-Manager → Model Manager**, or search Hugging Face for
> `Comfy-Org z_image_turbo`.

### What each file does

- **`z_image_turbo_nvfp4`** — nvfp4-quantized turbo checkpoint. 8 steps / CFG 1.0.
  Daily-driver path for txt2img and logo modes. Best speed/quality ratio.
- **`z_image_bf16`** — full bf16 base checkpoint. 25 steps / CFG 4.0. Used by
  default for product img2img (always) and for txt2img/logo when `--variant base`
  is passed. Maximum fidelity.
- **`qwen_3_4b`** — the shared Qwen-3-4B text encoder. Load via
  `CLIPLoader(type="lumina2")`. Required for all three Z-Image modes.
- **`ae`** — the Z-Image VAE. Shared between turbo and base. Load via `VAELoader`.

### Variant pairing

The variant flag determines both the model file and the sampler settings.
**Do not mix** — the turbo model at 25 steps or the base model at 8 steps / CFG 1.0
both degrade output:

| `--variant` | Model | Steps | CFG | Default for |
|-------------|-------|-------|-----|-------------|
| `turbo` | `z_image_turbo_nvfp4.safetensors` | 8 | 1.0 | txt2img, logo |
| `base` | `z_image_bf16.safetensors` | 25 | 4.0 | product (always) |

---

## Upscaler (optional — `--upscale`)

The `--upscale` flag adds a 4× ESRGAN pass before `SaveImage`. The default model
is **4x-UltraSharp** (an ESRGAN `.pth`); drop it into `upscale_models/`.

| File | Destination (`ComfyUI/models/…`) | Source | License |
|------|----------------------------------|--------|---------|
| `4x-UltraSharp.pth` | `upscale_models/` | `https://huggingface.co/lokCX/4x-Ultrasharp` | ❓ verify (repo lists it; recorded neutrally) |

> Override per-render with `--upscale-model <name>`, or per-brand via
> `defaults.upscale_model` in `brand.yaml`. The filler falls back to
> `4x-UltraSharp.pth` when neither is set.

---

## FLUX.2 (secondary)

FLUX.2 [dev] (Klein) — activates when the model name starts with `flux2`. Uses a
**split loader**: a diffusion transformer + a Mistral-3 text encoder + a VAE
(not an all-in-one checkpoint; `CheckpointLoaderSimple` will not work).

| File | Destination (`ComfyUI/models/…`) | Source | License |
|------|----------------------------------|--------|---------|
| `flux2_dev_fp8mixed.safetensors` | `diffusion_models/` | `Comfy-Org/FLUX.2` repackage (Hugging Face) | ❓ FLUX.2 [dev] non-commercial — verify; fine for personal use |
| `mistral_3_small_flux2_bf16.safetensors` | `text_encoders/` | `Comfy-Org/FLUX.2` text encoders (Hugging Face) | ✅ Mistral / Apache-2.0 |
| `flux2-vae.safetensors` | `vae/` | `Comfy-Org/FLUX.2` repo (Hugging Face) | ❓ FLUX.2 [dev] |

> Find them via the ComfyUI **Templates Library** (it links the exact downloads),
> or **ComfyUI-Manager → Model Manager**, or search Hugging Face for
> `Comfy-Org FLUX.2`.

### Faster / lighter FLUX.2 variants (optional)

- **NVFP4 (RTX 50-series / Blackwell only):**
  `flux2-dev-nvfp4-mixed.safetensors` from
  [`black-forest-labs/FLUX.2-dev-NVFP4`](https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4)
  → `diffusion_models/`. Measured **~2.7× faster** than fp8 at equal quality on
  an RTX 5090 — **requires the cu130 stack** (see
  [`../../docs/BLACKWELL-TUNING.md`](../../docs/BLACKWELL-TUNING.md)). On CUDA 12.x
  it runs *slower* than fp8; only use it after confirming cu130.

### FLUX.2 VRAM

- fp8 (`flux2_dev_fp8mixed`): ~16–24 GB; ~12 GB load footprint observed.
- NVFP4: smaller footprint, faster, **cu130 only**.
- Tight on VRAM? Use GGUF/quantized variants via `ComfyUI-GGUF`.
