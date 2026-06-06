# `image` — text-to-image (FLUX.2)

A **tested, importable** FLUX.2 [dev] text-to-image workflow. This isn't a
hand-waved graph — it was built from the live ComfyUI node schemas and run
end-to-end on an RTX 5090 (1024×1024, 20 steps).

## Files
- [`workflow.template.json`](workflow.template.json) — the ComfyUI **API-format**
  workflow (drop-in for `POST /prompt` or any MCP `enqueue_workflow` tool). A copy
  also lives in [`../../workflows/templates/flux2-txt2img.json`](../../workflows/templates/flux2-txt2img.json).
- [`models.md`](models.md) — the three model files you need + where to get them.

## Use it
1. Download the models in [`models.md`](models.md) into your `ComfyUI/models/...` folders.
2. **In the ComfyUI UI:** drag `workflow.template.json` onto the canvas, edit the
   prompt, hit Run. *(If your filenames differ, re-pick them in the loader nodes.)*
3. **Programmatically / via MCP:** send the JSON to `POST /prompt`, or hand it to an
   MCP `enqueue_workflow` tool. It's already in API format — no conversion needed.

## Why FLUX.2 needs this exact graph (the gotchas)
FLUX.2 trips people up because it's **not** a normal checkpoint:
- It's **split** into three loaders: `UNETLoader` (the diffusion model) +
  `CLIPLoader` with **`type: "flux2"`** (the Mistral-3 text encoder) + `VAELoader`.
  `CheckpointLoaderSimple` will *not* work.
- The latent is **`EmptySD3LatentImage`** (16-channel), not `EmptyLatentImage`.
- Guidance is a dedicated **`FluxGuidance`** node (default `3.5`) on the positive
  conditioning — and **`cfg` is `1`** (FLUX.2 is guidance-distilled; real CFG is off).
- Sampler/scheduler that work well: **`euler` / `simple`**, ~20 steps.

## Performance
- fp8 (`flux2_dev_fp8mixed`) @ 1024² / 20 steps: **~22.7 s** warm on an RTX 5090.
- **NVFP4** variant on the cu130 stack: **~8.4 s** — *2.7× faster, same quality.*
  See [`../../docs/BLACKWELL-TUNING.md`](../../docs/BLACKWELL-TUNING.md) to unlock it,
  and [`models.md`](models.md) for the file.
- First render of a session is slower (model load + one-time SageAttention/Triton
  JIT); keep the model resident for fast iteration.

## VRAM
~16–24 GB for fp8. Less for NVFP4/GGUF. See [`models.md`](models.md).
