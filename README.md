# 🐉 Chimera

> Multimodal generative pipeline on ComfyUI — image, video, 3D, and audio, orchestrated through an MCP agent layer.

One pipeline, many beasts. Chimera is a **modular** set of ComfyUI workflows and
orchestration glue spanning **image, video, 3D, and audio** generation, with an
**LLM/agent layer** that can drive the whole thing via MCP.

It's **public and reusable** — fork it, take the modules you need, ignore the
rest. Personal and brand-specific workflows are kept out of the repo by design
(see [Privacy model](#privacy-model)).

## Modules
| Module | What it does | Notes |
|--------|--------------|-------|
| `image` | Text-to-image, editing, ControlNet, IP-Adapter, upscale | See `docs/CATALOG.md` |
| `video` | Text-to-video, image-to-video, audio-video | LTX-2 / WAN / Hunyuan |
| `audio` | Music, SFX, speech/TTS | ACE-Step / Stable Audio |
| `threed` | Image-to-3D meshes & relief | Hunyuan3D 2.1 (local) |
| `agent` | LLM prompt expansion, VLM self-correction, MCP server | Orchestration |

Each module is self-contained: a README, a sanitized `workflow.template.json`,
and a `models.md` listing the models + download sources + licenses.

## Quickstart
1. Install ComfyUI (see `docs/SETUP.md` — Blackwell/RTX 50-series needs the
   `cu128` build).
2. Pick a module and read its `README.md`.
3. Download the models listed in that module's `models.md`.
4. Import its `workflow.template.json` via the ComfyUI workflow menu.
5. Copy it into `workflows/personal/` and customize — your version stays private.

## Privacy model
This repo is public but your work doesn't have to be:
- **Tracked & shareable:** `workflows/templates/`, all `modules/`, docs, scripts.
- **Private (gitignored):** `workflows/personal/**`, any `*.local.json`,
  `outputs/`, `models/`, `.env`.

Name any private workflow `*.local.json` and it's ignored automatically, anywhere
in the tree.

## Best free templates & models
See **[`docs/CATALOG.md`](docs/CATALOG.md)** for the current best
locally-runnable models per modality — chosen on quality / fitness for the task,
with VRAM needs and official download sources (license info is reference-only, not a
selection constraint). Start with ComfyUI's built-in **Templates Library** (sidebar)
for one-click reference workflows.

## Hardware
Developed on an RTX 5090 (32 GB). Most modules run on far less via quantized
(GGUF / NVFP8) weights — per-module VRAM notes are in each `models.md`.

## License
Code/templates in this repo: see `LICENSE`. Models are licensed separately — see
`docs/CATALOG.md` for each model's terms (informational; this project is personal
use, so licensing doesn't gate model choice).
