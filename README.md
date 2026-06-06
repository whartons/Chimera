# 🐉 Chimera

> A modular ComfyUI toolkit — with a battle-tested **RTX 50-series tuning guide**, a
> **working FLUX.2 workflow**, and a hardened **MCP bridge** to drive ComfyUI from an
> AI assistant. Building toward image · video · 3D · audio under one roof.

Chimera is a **public, reusable** set of ComfyUI workflows, docs, and orchestration
glue. Fork it, take what's useful, ignore the rest. It's developed on an RTX 5090 but
written to help anyone running ComfyUI — especially on **Blackwell (RTX 50-series)**.

## ✅ What's here today (tested, not vapor)

- **[RTX 50-series / Blackwell tuning guide](docs/BLACKWELL-TUNING.md)** — the part
  most people get wrong. cu130 to unlock comfy-kitchen's FP4 kernels, SageAttention,
  `--fast`, and NVFP4 — with **measured numbers** (FLUX.2: **8.4 s vs 22.7 s, a 2.7×
  speedup at equal quality** on a 5090) and the non-obvious **`Comfy.Server.LaunchArgs`**
  trick for passing flags to ComfyUI **Desktop**. If you own a 50-series card, start here.
- **[Working FLUX.2 text-to-image workflow](modules/image/)** — an importable,
  **API-format** graph built from the live node schemas and actually run end-to-end.
  FLUX.2 is fiddly (split loaders, `type: "flux2"` CLIP, `EmptySD3LatentImage`,
  `FluxGuidance`, `cfg 1`); this just works. See [`workflows/templates/flux2-txt2img.json`](workflows/templates/flux2-txt2img.json).
- **[MCP agent bridge](modules/agent/)** — wire `comfyui-mcp` to an AI assistant
  (Claude Code) so it can introspect nodes, build/queue workflows, and fetch results.
  Includes a **security audit summary + hardening** (`--omit=optional`, per-tool
  approval gates) so you adopt third-party MCP code with eyes open.

## 🗺️ Roadmap (scaffolded, not done yet)
| Module | Status |
|--------|--------|
| `image` | ✅ FLUX.2 txt2img working |
| `agent` | ✅ MCP bridge + security model |
| `video` | ⬜ planned — LTX-2 / WAN / Hunyuan |
| `threed` | ⬜ planned — Hunyuan3D 2.1 |
| `audio` | ⬜ planned — ACE-Step / Stable Audio |

See **[`docs/CATALOG.md`](docs/CATALOG.md)** for the best free, locally-runnable
models per modality (with VRAM needs + sources), and **[`docs/SETUP.md`](docs/SETUP.md)**
for install notes.

## Quickstart
1. Install ComfyUI ([`docs/SETUP.md`](docs/SETUP.md) — RTX 50-series wants the
   CUDA 12.8+/cu130 build).
2. **5090 owner?** Run the [tuning guide](docs/BLACKWELL-TUNING.md) — it pays for itself.
3. Try the image module: download the models in [`modules/image/models.md`](modules/image/models.md),
   then import [`workflows/templates/flux2-txt2img.json`](workflows/templates/flux2-txt2img.json).

## Privacy model
Public repo, private work. **Tracked & shareable:** `workflows/templates/`, all
`modules/`, docs, scripts. **Gitignored:** `workflows/personal/**`, any `*.local.json`,
`outputs/`, `models/`, `.env`. Name any private workflow `*.local.json` and it's
ignored anywhere in the tree.

## Hardware
Developed on an RTX 5090 (32 GB). Most things run on far less via quantized
(GGUF / NVFP8 / NVFP4) weights — see each module's `models.md`.

## License
Code/templates in this repo: see `LICENSE`. Models are licensed separately — see
[`docs/CATALOG.md`](docs/CATALOG.md) for each model's terms.
