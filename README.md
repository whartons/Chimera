# Chimera

![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
[![tests](https://github.com/whartons/ComfyUI-Chimera/actions/workflows/ci.yml/badge.svg)](https://github.com/whartons/ComfyUI-Chimera/actions/workflows/ci.yml)
![ComfyUI](https://img.shields.io/badge/ComfyUI-%E2%89%A50.24-orange)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)
![Built on RTX 5090 · cu130](https://img.shields.io/badge/built%20on-RTX%205090%20%C2%B7%20cu130-76B900?logo=nvidia&logoColor=white)

> A modular, **brand-aware** ComfyUI pipeline — **image · video · audio · 3D under one CLI** —
> with a **generate → VLM-judge → refine self-correction loop**, **reproducible replay** of any
> render, and a battle-tested **RTX 50-series tuning guide**. Built and run end-to-end on an RTX 5090.

![An ember-winged chimera — lion, goat, and serpent-headed tail — over an erupting volcano, generated with this repo's Z-Image workflow on an RTX 5090](docs/images/chimera-zimage-sample.png)
<sub>↑ A proper chimera — lion body, a goat head from the back, a serpent-headed tail, and ember-lit dragon wings — over an erupting volcano. Generated with the included [Z-Image workflow](workflows/templates/brand-zimage-txt2img.json) (`--variant base`) on an RTX 5090, straight out of ComfyUI.</sub>

Chimera is a **public, reusable** set of ComfyUI workflows, docs, and orchestration glue. Fork it,
take what's useful, ignore the rest. It's developed on an RTX 5090 but written to help anyone running
ComfyUI — especially on **Blackwell (RTX 50-series)**.

## ✅ What's here today (tested, not vapor)

- **🤖 An agent self-correction loop** *(the headline)* — Chimera doesn't just generate once, it
  *iterates to a passing result*: build a brand rubric → generate → a **VLM judges the output against
  the rubric** → unmet criteria are fed back into the prompt → regenerate until it passes or hits an
  iteration cap. A **judge-agnostic, model-free core** (unit-tested, no GPU) with two interchangeable
  backends: a **headless local Qwen2.5-VL-7B** judge, and an **assistant multi-judge-consensus** pass.
  Live-validated end-to-end. See [`modules/agent/self-correction.md`](modules/agent/self-correction.md).
- **One CLI, four modalities** — [`scripts/generate.py`](scripts/generate.py) drives **image, video,
  audio, and 3D** through a shared brand-aware core (manifest → prompt → validated graph → ComfyUI →
  per-brand output). Every graph was built from live node schemas and run end-to-end on a 5090.
- **Reproducible by construction** — every render writes a schema-versioned **sidecar** JSON, and
  `generate.py replay <sidecar>.json` re-runs the *identical* render (prompt, seed, model, inputs).
- **Quality + onboarding polish** — image/video `--upscale` (4× ESRGAN / 2× LTX latent), a
  `new-brand` scaffolder, and a `lint` validator that catches brand-config mistakes early.
- **[RTX 50-series / Blackwell tuning guide](docs/BLACKWELL-TUNING.md)** — the part most people get
  wrong. cu130 to unlock comfy-kitchen's FP4 kernels, SageAttention, `--fast`, NVFP4 — with **measured
  numbers** (FLUX.2: **8.4 s vs 22.7 s, a 2.7× speedup at equal quality** on a 5090) and the
  non-obvious **`Comfy.Server.LaunchArgs`** trick for passing flags to ComfyUI **Desktop**.
- **[Brand Kits](brands/)** — keep each brand's reference art + a YAML "brand brain" in one folder and
  generate **on-brand** assets (prompt injection + alpha-exact logo overlay + product re-render +
  optional LoRA), routed to per-brand output folders. The *pattern* is public; your brand data stays
  gitignored. See [`modules/image/brand-kits.md`](modules/image/brand-kits.md).
- **A hardened [MCP bridge](modules/agent/)** — drive ComfyUI from an AI assistant through a
  **pinned, security-audited** third-party MCP server, with per-tool approval gates.

**183 GPU-free unit tests** (mocked ComfyUI client) keep the core green without a GPU.

## 🧩 Modules
| Module | Backend | Status |
|--------|---------|--------|
| [`image`](modules/image/) | Z-Image (default) · FLUX.2 (secondary) — txt2img / logo / product · `--upscale` | ✅ |
| [`video`](modules/video/) | LTX-2.3 image-to-video + native synced audio · `--upscale` | ✅ |
| [`audio`](modules/audio/) | ACE-Step (music) · HunyuanVideo-Foley (video → SFX) | ✅ |
| [`threed`](modules/threed/) | Hunyuan3D 2.1 image → mesh (GLB / STL / OBJ) | ✅ |
| [`agent`](modules/agent/self-correction.md) | **Self-correction loop** (generate → VLM judge → refine) | ✅ |
| [`agent`](modules/agent/) | MCP bridge + security model | ✅ |

## 🏗️ Architecture / engineering highlights

The parts an engineer (or hiring manager) might want to see:

- **One brand-aware core, per-modality fillers.** `manifest → prompt → validated graph → ComfyUI →
  routed output` is shared; each modality plugs in a small "filler" that builds its API-format graph.
  Nodes are addressed by a **stable `_meta.title`, not numeric id**, so re-saving a graph in ComfyUI
  can't break the fillers.
- **The agent loop is a clean abstraction.** `run_loop` depends only on a `Judge` interface, a
  `PromptExpander` interface, and an injected `generate` callable — so the whole generate→judge→refine
  loop is **fully unit-testable with no ComfyUI, no GPU, no model**, and the local-VLM and
  assistant-consensus backends slot in behind the same seam.
- **Reproducibility is a first-class feature.** Schema-versioned sidecars capture the *resolved* inputs
  + the *actual* graph prompt/negative; `replay` reconstructs the run; an `agent-run` sidecar is
  explicitly marked so it can't be mistaken for a replayable render.
- **Third-party code is treated as untrusted.** The MCP server and every custom node pack are
  **read, adversarially audited, and pinned to an exact version or commit** before adoption, with
  per-tool approval gates on the dangerous tools — never `@latest`.
- **Tested without a GPU.** 183 tests run against a mocked ComfyUI client, so correctness of the
  graph-building, routing, sidecar, replay, scaffolder, and agent-loop logic is verifiable in CI-time.

## ⚡ Generate — one CLI, four modalities

```bash
# image  (Z-Image default; --variant base|turbo; --model flux2… switches to FLUX.2; opt-in --watermark)
python scripts/generate.py image --brand <brand> --mode txt2img --subject "an armored rover" --watermark
python scripts/generate.py image --brand <brand> --mode product --asset rover.png    # img2img restyle
python scripts/generate.py image --brand <brand> --mode txt2img --subject "…" --upscale   # 4× ESRGAN
# video  (image-to-video with synced audio; --upscale = 2× LTX spatial latent upscaler)
python scripts/generate.py video --brand <brand> --from-image rover.png --subject "rolls forward, dust"
# audio  (music = text→stinger; foley = video→SFX muxed back onto the clip)
python scripts/generate.py audio --brand <brand> --mode music --subject "logo sting"
python scripts/generate.py audio --brand <brand> --mode foley --from-video clip.mp4 --subject "tires on gravel"
# 3D  (image→mesh; export glb | stl | obj)
python scripts/generate.py 3d --brand <brand> --from-image rover.png --format stl
```

Outputs route to `brands/<brand>/outputs/{images,video,audio,3d}/` (organized by media type), each with
a reproducibility sidecar — **moved** into the brand folder, never duplicated to the global `outputs/`.
The opt-in `--watermark` composites the brand logo in-graph (off by default).

## 🔁 Reproducibility & replay

Every output ships a `<output>.json` sidecar recording the resolved seed, model, prompt/negative, and
inputs. Re-run any render exactly:

```bash
python scripts/generate.py replay brands/<brand>/outputs/images/<name>.json   # [--seed N] to vary
```

It reconstructs the CLI inputs from the sidecar and re-derives the prompt through the same brand-aware
path — so with an unchanged `brand.yaml` you get the identical render.

## 🆕 Spin up a new brand

```bash
python scripts/generate.py new-brand <name>      # scaffold from brands/_template/ (your brand stays gitignored)
python scripts/generate.py lint --brand <name>   # validate brand.yaml + referenced assets before you render
```

### 🖼️ Example showcase — the `example-brand`
The tracked **[`example-brand`](brands/example-brand/)** (an engineering-framed demo brand, "Mercury
Tactical Systems") is generated entirely by the commands above:

| `txt2img` | `product` (img2img) | `logo` overlay |
|:---:|:---:|:---:|
| ![txt2img](brands/example-brand/outputs/images/example-brand_txt2img_7.png) | ![product](brands/example-brand/outputs/images/example-brand_product_7.png) | ![logo](brands/example-brand/outputs/images/example-brand_logo_7.png) |

…plus a [video clip](brands/example-brand/outputs/video/example-brand_i2v_42.mp4) (LTX-2.3, synced
audio), the same clip [re-foleyed](brands/example-brand/outputs/video/example-brand_foley_42.mp4) with
realistic SFX, a [music stinger](brands/example-brand/outputs/audio/example-brand_music_42.mp3), and a
[3D mesh](brands/example-brand/outputs/3d/example-brand_image_42.glb).

**Brand consistency across subjects** — the same brand "brain" drives a whole fleet (in
[`outputs/branded/`](brands/example-brand/outputs/branded/)):

| recon-drone | quadruped | sensor-tower | tracked-utility |
|:---:|:---:|:---:|:---:|
| ![recon-drone](brands/example-brand/outputs/branded/recon-drone.png) | ![quadruped](brands/example-brand/outputs/branded/quadruped.png) | ![sensor-tower](brands/example-brand/outputs/branded/sensor-tower.png) | ![tracked-utility](brands/example-brand/outputs/branded/tracked-utility.png) |

See **[`docs/CATALOG.md`](docs/CATALOG.md)** for the best free, locally-runnable models per modality
(with VRAM needs + sources), and **[`docs/SETUP.md`](docs/SETUP.md)** for install notes.

## Quickstart
1. Install **ComfyUI ≥ 0.24** ([`docs/SETUP.md`](docs/SETUP.md) — RTX 50-series wants the
   CUDA 12.8+/cu130 build; the local agent judge uses a core node added in 0.24).
2. **5090 owner?** Run the [tuning guide](docs/BLACKWELL-TUNING.md) — it pays for itself.
3. Download a module's models (e.g. [`modules/image/models.md`](modules/image/models.md)).
4. Try it on the demo brand, or scaffold your own:
   ```bash
   python scripts/generate.py image --brand example-brand --mode txt2img \
       --subject "an armored rover" --comfy-output-dir outputs
   python scripts/generate.py new-brand my-brand   # then edit brands/my-brand/brand.yaml + lint it
   ```

## Privacy model
Public repo, private work. **Tracked & shareable:** `workflows/templates/`, all `modules/`, docs,
scripts. **Gitignored:** `workflows/personal/**`, any `*.local.json`, real brands under `brands/`,
`outputs/`, `models/`, `.env`. Name any private workflow `*.local.json` and it's ignored anywhere.

## 🔒 Security & maintenance (third-party code)
The MCP server and the custom node packs run third-party code with your privileges, so Chimera treats
them as **untrusted-by-default** and keeps them on a short leash:

- **Pinned + audited — never `@latest`.** Each third-party dependency (the `comfyui-mcp` server, the
  Qwen-VL judge pack, the foley pack) is read through and adversarially audited before adoption, then
  pinned to an exact version or commit. A floating tag could change under you between runs; a pin can't.
- **Hardened launch.** `NPM_CONFIG_OMIT=optional` keeps optional tunnel / cloud / LLM-SDK dependencies
  off your machine entirely.
- **Per-tool approval gates.** The code-execution / process-control / destructive MCP tools force an
  explicit prompt on every call via [`.claude/settings.json`](.claude/settings.json); read-only and
  generation tools stay frictionless.

**Reusable takeaway:** if you adopt *any* community MCP server or node pack, pin it, audit it, gate the
dangerous tools, and re-scan on a cadence instead of tracking `@latest`.

## Hardware
Developed on an RTX 5090 (32 GB), **cu130 / torch 2.10** reference build. Most things run on far less
via quantized (GGUF / NVFP4 / fp8) weights — see each module's `models.md`.

## License
MIT — see [`LICENSE`](LICENSE). Models are licensed separately; see
[`docs/CATALOG.md`](docs/CATALOG.md) for each model's terms.
