# Brand Kits — how brand-aware generation works

Brand Kits turns a folder of reference art + a `brand.yaml` manifest into **on-brand**
generations. This is the design/internals doc; for day-to-day usage see
[`../../brands/README.md`](../../brands/README.md).

## The package

Pure logic lives in `scripts/brandkit/` (importable, unit-tested, **no live ComfyUI
needed**); two thin CLIs wire it together:

| File | Responsibility |
|---|---|
| `brandkit/manifest.py` | Load + validate `brand.yaml` → typed `BrandManifest` |
| `brandkit/prompt.py` | Weave brand style/palette/prefix/suffix into the prompt (mechanism ①) |
| `brandkit/workflow.py` | Load a template, inject prompt/size/seed, LoRA node, logo geometry |
| `brandkit/comfy.py` | Minimal ComfyUI HTTP client (queue → poll → list outputs) |
| `brandkit/outputs.py` | Route a finished render into `brands/<brand>/outputs/`; empty-output guard (`first_output`) + reproducibility `write_sidecar`. |
| `brandkit/training.py` | Dataset scan + training-config generation (pure) |
| `brandkit/nodes.py` | Title-based node addressing (resolve nodes by title, not raw id) |
| `brandkit/watermark.py` | Opt-in in-graph watermark (enabled via `--watermark` flag) |
| `scripts/generate.py` | Unified CLI (`image` subcommand; per-modality subcommands) |
| `scripts/train_brand_lora.py` | LoRA trainer scaffold CLI (dry-run by default) |

Everything except `comfy.py` is testable without a server, so `python -m pytest`
covers the whole core offline.

## The three on-brand mechanisms

**① Prompt injection — always on.** `build_prompt()` composes
`prefix → subject → style → palette → suffix` into the positive prompt. Zero downloads;
works for every brand immediately. This is the backbone — even brands with no logo/LoRA
get consistent look from style + palette words.

The manifest `negative` goes into the image and video graphs' negative text (video appends its own
family's list) and the sidecar records what the graph carries. Z-Image has no negative text (it zeroes
its negative with `ConditioningZeroOut`, even the CFG-4 `base` variant, so its sidecars record `""`), and
audio never takes it: music and sfx have no text negative (Stable Audio 3's stays empty, ACE-Step zeroes
its conditioning), and foley uses `audio.foley_negative` instead.

No image recipe samples with it: Qwen-Image-2.1 and FLUX.2 run at CFG 1, where ComfyUI skips the negative
pass entirely. It changes the output only for video sampled **above CFG 1**: LTX-2.3 and Wan 2.2
`--quality full`. To keep something out of an image, word the positive instead. The self-correction loop
does use it: the rubric asks the judge to confirm the render avoids these traits, `brand_guard` drops any
FIX `add` term that names one, and a brand with only a negative still gets the loop's subject correction.

**② IP-Adapter style/subject reference — V2, opt-in (deferred).** The manifest already
carries an `ip_adapter{}` block (parsed, `enabled: false` by default). FLUX.2 IP-Adapter
+ clip-vision tooling is nascent and needs model downloads, so it's isolated behind the
toggle and lands in a separate V2 plan — adding it doesn't disturb V1.

**③ Brand LoRA — opt-in per brand.** Two halves:
- **Load** (in V1): set `lora.file` in `brand.yaml` and the workflow filler injects a
  `LoraLoaderModelOnly` node and re-points the sampler at it. No file → no node.
- **Train** (scaffold): `train_brand_lora.py` scans `training/` (image + matching `.txt`
  caption), generates a backend config, and — with `--run` — invokes a pluggable backend.
  Defaults to `--dry-run` so the plumbing is verifiable now; real FLUX.2 LoRA training is
  bleeding-edge, so you attach a backend (e.g. ai-toolkit) when it's ready.

## Modes → templates

`--mode` selects one of four generic, API-format graphs in `workflows/templates/`: `txt2img`, `logo`
and `product` (table below), plus `relight`, which always uses FLUX.2 (`brand-flux2-relight.json`). The
**default backend is Qwen-Image-2.1**. The filler picks the graph family from the model name:
`qwen_image*` → the `brand-qwen-image-*` graphs, `z_image*` → `brand-zimage-*`, and `flux2*` → the
FLUX.2 graphs. It addresses nodes by a stable `_meta.title` (see `brandkit/nodes.py`), so re-saving
a graph in ComfyUI can't silently misroute an edit.

| Mode | Template (default · Qwen-Image-2.1) | What it does |
|---|---|---|
| `txt2img` | `brand-qwen-image-txt2img.json` | on-brand text-to-image |
| `logo` | `brand-qwen-image-logo-overlay.json` | txt2img → composite `logos/<png>` (alpha-correct) at a corner |
| `product` | `brand-qwen-image-product.json` | reference edit: the encoder sees `products/<png>` and places that product in a new scene at the brand's size |

The earlier backends stay one setting away: set the model in `brand.yaml` or pass `--model`
(see [`../../docs/CATALOG.md`](../../docs/CATALOG.md)). **Z-Image** (`z_image_turbo_*`, the
default before v0.6.0) uses the `brand-zimage-*` graphs; its `product` mode is an img2img
re-render at the product photo's size. **FLUX.2** (`flux2*`) uses `brand-txt2img.json` /
`brand-logo-overlay.json` / `brand-product-mockup.json`, and is also what `--mode relight` runs on.

The logo overlay uses `LoadImage`'s mask output as the composite alpha and computes
x/y from `logo.position` + `logo.margin` against the canvas, so the logo stays
pixel-exact (generative models can't reliably redraw a logo; compositing keeps it true).

## Per-brand outputs

ComfyUI has a single global output directory. Rather than fight that, the orchestrator
lets `SaveImage` write there, then **relocates** the finished file into
`brands/<brand>/outputs/images/<brand>_<mode>_<seed>.png` (`outputs.route_output` groups
outputs by media type: `images/ video/ audio/ 3d/`). That keeps
every brand's renders adjacent to its source art while `brands/**/outputs/` stays
gitignored. Pass `--comfy-output-dir` so the orchestrator knows where to pick the file up.

## Testing

```bash
python -m pytest             # the offline core: manifest, prompt, workflow, outputs, comfy, training
```

End-to-end generation (needs a running ComfyUI at `127.0.0.1:8000` with the relevant
models) is exercised against the tracked `brands/example-brand/`, whose committed
outputs + reproducibility sidecars were produced by the CLI. The 3D mesh was then slimmed with
`chimera render --mode finish` (textures kept); its sidecar describes the TRELLIS.2 render it came from.
