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

Everything except `comfy.py` is testable without a server, so `python -m pytest -q`
covers the whole core offline.

## The three on-brand mechanisms

**① Prompt injection — always on.** `build_prompt()` composes
`prefix → subject → style → palette → suffix` into the positive prompt and uses the
manifest `negative`. Zero downloads; works for every brand immediately. This is the
backbone — even brands with no logo/LoRA get consistent look from style + palette words.

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

`--mode` selects one of three generic, API-format FLUX.2 graphs in
`workflows/templates/` (the filler addresses nodes by a stable `_meta.title` (see `brandkit/nodes.py`), so re-saving a graph in ComfyUI can't silently misroute an edit):

| Mode | Template | What it does |
|---|---|---|
| `txt2img` | `brand-txt2img.json` | on-brand text-to-image (the verified FLUX.2 graph) |
| `logo` | `brand-logo-overlay.json` | txt2img → composite `logos/<png>` (alpha-correct) at a corner |
| `product` | `brand-product-mockup.json` | img2img: re-render `products/<png>` into a new scene |

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
python -m pytest -q          # the offline core: manifest, prompt, workflow, outputs, comfy, training
```

End-to-end generation (needs a running ComfyUI at `127.0.0.1:8000` with the relevant
models) is exercised against the tracked `brands/example-brand/`, whose committed
outputs + reproducibility sidecars are produced entirely by the CLI.
