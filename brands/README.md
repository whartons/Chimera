# Brand Kits — per-brand reference art + a YAML "brand brain"

Keep each brand/business/project's reference art and identity in one folder, then
generate **on-brand** images from it. The *pattern* is public and reusable; your
actual brand folders stay **private** (gitignored). One tracked example brand,
`example-brand/` (Mercury Tactical Systems), is the public pilot the pipeline is
validated against.

## What's tracked vs private

| Path | Tracked? |
|---|---|
| `brands/README.md` | ✅ tracked |
| `brands/_template/` | ✅ tracked (copy this to start a brand) |
| `brands/example-brand/` | ✅ tracked (public pilot, sans `outputs/`) |
| `brands/<your-brand>/` | 🔒 **gitignored** — your brand data is private |
| `brands/**/outputs/` | 🔒 **gitignored** everywhere (generated media) |

The rules live in [`../.gitignore`](../.gitignore): everything under `brands/` is
ignored *except* the three tracked paths above, and every `outputs/` subfolder is
always ignored.

## Start a brand

```bash
cp -r brands/_template brands/my-brand          # PowerShell: Copy-Item -Recurse brands\_template brands\my-brand
# edit brands/my-brand/brand.yaml, then drop art into:
#   logos/       exact PNG logos to composite (alpha = transparency)
#   products/    product photos to re-render into scenes
#   references/  loose inspiration (style direction; used by the V2 IP-Adapter path)
#   training/    images (+ matching .txt captions) for an optional brand LoRA
#   lora/        a trained brand LoRA lands here
```

## `brand.yaml` — the brand brain

```yaml
name: "My Brand"
style: "the look in a few words: palette, mood, lighting, rendering"
palette: ["#1c1f22", "#c8442e"]     # optional; described to the model
prompt_prefix: ""                    # prepended to every subject
prompt_suffix: ", studio product render"
negative: "low quality, blurry, watermark"
defaults: { model: "flux2_dev_fp8mixed.safetensors", width: 1024, height: 1024, steps: 20, guidance: 3.5 }
logo:  { default: "logos/primary.png", position: "bottom-right", scale: 0.18, margin: 0.04 }
lora:  { file: null, strength: 0.8 }          # set file to a .safetensors to auto-load it
ip_adapter: { enabled: false, weight: 0.5, references: "references/" }   # V2, off by default
```

See [`_template/brand.yaml`](_template/brand.yaml) for the annotated starter and
[`example-brand/brand.yaml`](example-brand/brand.yaml) for a filled-in example.

## Generate (the orchestrator)

`scripts/generate.py image` reads the manifest, weaves the brand into the prompt,
picks the right workflow, queues it to ComfyUI, and routes the result into
`brands/<brand>/outputs/`.

```bash
# 1) text-to-image, on-brand
python scripts/generate.py image --brand example-brand \
    --subject "a heavy combat support rig, articulated legs" \
    --mode txt2img --seed 7 \
    --comfy-output-dir "C:/Users/<you>/.../Chimera/outputs"
    # (add --watermark to stamp the brand logo)

# 2) logo watermark (stamps logos/primary.png as an alpha-correct corner mark)
python scripts/generate.py image --brand example-brand \
    --subject "the armored six-wheel recon rover, clean studio product shot, dark seamless background" \
    --mode logo --asset primary.png --comfy-output-dir "<ComfyUI output dir>"

# 3) product mockup (re-renders products/<file> into a new scene, img2img)
python scripts/generate.py image --brand example-brand \
    --subject "on a tactical staging table, soft rim light" \
    --mode product --asset rover.png --comfy-output-dir "<ComfyUI output dir>"
```

`--comfy-output-dir` is where your ComfyUI writes (its `SaveImage` dir); the
orchestrator moves the finished file from there into the brand's `outputs/`.

## Optional: train a brand LoRA

```bash
python scripts/train_brand_lora.py --brand example-brand          # dry-run: writes config, no training
python scripts/train_brand_lora.py --brand example-brand --run    # invokes a pluggable backend (must be installed)
```

The trainer is a **backend-pluggable scaffold** (dry-run by default) — FLUX.2 LoRA
training tooling is still bleeding-edge, so the plumbing (dataset scan, caption
pairing, config generation) is verifiable today and you wire in a backend when ready.

The three mechanisms, the orchestrator internals, and the trainer caveats are
documented in [`../modules/image/brand-kits.md`](../modules/image/brand-kits.md).
