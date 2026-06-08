# `threed` — image-to-3D mesh generation

Takes a single input image and produces a 3D mesh exported as a `.glb` file.
Powered by **Hunyuan3D 2.1** running on native ComfyUI 0.22.3 nodes — no custom
node pack required, no gated model dependencies.

## Files

- [`workflow.template.json`](workflow.template.json) — ComfyUI **API-format**
  workflow for the Hunyuan3D 2.1 image→3D path. A copy also lives in
  [`../../workflows/templates/brand-3d-image.json`](../../workflows/templates/brand-3d-image.json).
- [`models.md`](models.md) — the one required checkpoint, HF repo, destination,
  and license note.

## Use it — CLI

```
python scripts/generate.py 3d \
  --brand <brand> \
  --from-image product.png \
  --seed 42 \
  [--octree 256] \
  [--format glb|stl|obj] \
  [--comfy-output-dir <dir>]
```

- `--from-image` is the source image (a file in `brands/<brand>/products/`,
  `references/`, or `outputs/images/`; searched in that order).
- `--octree` sets `VAEDecodeHunyuan3D`'s `octree_resolution` (default `256`).
  Higher values produce denser geometry at the cost of VRAM and file size;
  lower values produce lighter meshes. See the `--octree` section below.
- `--format` picks the export format (default `glb`). ComfyUI only saves GLB,
  so `stl` and `obj` are converted **host-side** by `brandkit/mesh.py` (a
  dependency-free glTF→STL/OBJ writer). All three carry geometry only — use
  `glb` for viewing/sharing, `stl` for 3D printing, `obj` for CAD/Blender.
  (STL/OBJ of a dense mesh are large: the example rover is ~18 MB GLB, but
  ~53 MB STL / ~37 MB OBJ — generate them on demand rather than committing them.)
- There is **no `--subject`** — this modality is image-conditioned, not
  text-conditioned. The geometry is driven entirely by the input image.
- `--watermark` is silently ignored — there is no 2D canvas to composite onto.
- `--free-before` defaults ON for this modality, clearing resident image or
  video models before the 3D job starts.

Output routes to `brands/<brand>/outputs/3d/<brand>_image_<seed>.glb`.

## How it works

The graph uses **ComfyUI core nodes only** — all of the following ship with
ComfyUI 0.22.3 and require no additional installation:

1. **`ImageOnlyCheckpointLoader`** — loads `hunyuan_3d_v2.1.safetensors` from
   `models/checkpoints/`. This single file bundles the DiT shape model, a
   DINOv2 CLIP-Vision encoder (ungated — no Hugging Face token required), and
   the 3D VAE.
2. **`ModelSamplingAuraFlow(shift 1)`** — wraps the model for the AuraFlow
   sampler schedule (shift 1.0).
3. **`LoadImage`** — loads the input image.
4. **`CLIPVisionEncode(crop=center)`** — encodes the input image through the
   bundled DINOv2 CLIP-Vision encoder to produce the conditioning signal.
5. **`Hunyuan3Dv2Conditioning`** — converts the CLIP-Vision output into positive
   and negative conditioning tensors for the KSampler.
6. **`EmptyLatentHunyuan3Dv2`** — allocates the 3D latent buffer (4096
   resolution, batch size 1).
7. **`KSampler`** — 30 steps, CFG 5.0, euler sampler, normal scheduler.
8. **`VAEDecodeHunyuan3D(octree_resolution 256)`** — decodes the latent into a
   voxel field at the specified octree resolution.
9. **`VoxelToMesh(algorithm=surface net, threshold=0.6)`** — runs surface net
   marching to extract a triangle mesh from the voxel field.
10. **`SaveGLB`** — writes the mesh as a binary glTF v2 (`.glb`) file.

## Shape-only output — important caveat

**The native Hunyuan3D 2.1 pipeline produces geometry only.** The output GLB
contains POSITION and index data (typically ~421 K vertices / ~1.1 M triangles
at `octree_resolution 256`, valid glTF-v2). It does **not** include PBR
textures, materials, or vertex colors — the mesh will appear as an untextured
grey solid in most viewers.

This is a limitation of the current native ComfyUI path, not of Hunyuan3D in
general. PBR texturing (Hunyuan3D-Paint) would require a separate custom node
pack that is not yet part of this module. Downstream texturing in Blender,
Substance Painter, or similar tools works fine on the exported geometry.

### Why in-pipeline PBR texturing is deferred on this stack

Automatic Hunyuan3D-Paint texturing depends on a **compiled CUDA rasterizer**
(`custom_rasterizer` + a differentiable renderer), the same class of dependency
that blocks TRELLIS.2 here. On the **Blackwell / cu130 / PyTorch 2.10 / Python
3.12** reference box this is currently unworkable without a heavy toolchain build:

- **No matching prebuilt wheel.** Every published `custom_rasterizer` wheel
  targets **cu126 / PyTorch 2.6** (kijai's `ComfyUI-Hunyuan3DWrapper`,
  visualbruno's `ComfyUI-Hunyuan3d-2-1`) or at best **cu129 / PyTorch 2.8**. A
  PyTorch C++/CUDA extension is ABI-bound to the torch minor version it was built
  against, so a 2.6/2.8 wheel will not import under 2.10 — and a cu126 wheel
  carries no `sm_120` (Blackwell) kernels.
- **No from-source compile available out of the box.** Building the rasterizer
  for `sm_120` against the installed torch needs the standalone **CUDA Toolkit
  (`nvcc`)**, which is not installed (ComfyUI ships only PyTorch's bundled CUDA
  runtime, not a compiler). Installing the ~3 GB toolkit + compiling is a large,
  failure-prone change to a working ComfyUI and is intentionally not automated
  here.

**How to texture an exported mesh today** (all operate on the shape-only GLB):

1. **DCC tools** — import the GLB into Blender / Substance Painter / ZBrush and
   paint or bake materials. Reliable, no GPU-extension dependency.
2. **A cu126/torch2.6 environment** — run kijai's `ComfyUI-Hunyuan3DWrapper` or
   visualbruno's `ComfyUI-Hunyuan3d-2-1` (with their prebuilt rasterizer wheels)
   in a separate, matching ComfyUI, and texture the GLB there.
3. **Revisit when wheels catch up** — once a `custom_rasterizer` wheel ships for
   cu130 / torch 2.10 / `sm_120`, an in-pipeline `--texture` flag becomes a clean
   addition (the shape path here already produces a valid glTF-v2 mesh to paint).

## `--octree` — geometry detail vs file size

`octree_resolution` controls the resolution of the voxel grid used during
VAE decode. Higher = more triangles, more detail, larger file, more peak VRAM.

| `--octree` | Approximate triangles | Approximate GLB size |
|------------|----------------------|----------------------|
| 128        | ~280 K               | ~5–8 MB              |
| 256        | ~1.1 M               | ~18 MB               |
| 384        | ~2.5 M               | ~40 MB               |
| 512        | ~4.5 M               | ~70 MB               |

Default is `256`. Use `128` for lightweight previews; `384`+ for high-detail
hero assets (check VRAM headroom before going above `256` on cards with less
than 32 GB).

## VRAM

| Step | Approximate VRAM | Notes |
|------|-----------------|-------|
| Checkpoint load | ~7.4 GB | Single-file: DiT + DINOv2 + VAE |
| KSampler (30 steps) | ~8–10 GB peak | Scales with batch and latent res |
| VAEDecodeHunyuan3D | ~4–6 GB peak | Scales with `octree_resolution` |
| VoxelToMesh | CPU-side | Offloaded; not VRAM-bound |

Total peak is within the 32 GB reference card at `octree_resolution 256`.
`--free-before` (default ON) clears resident image/video models beforehand.
If you have a card with less VRAM, lower `--octree` to reduce decode pressure.

## Why Hunyuan3D 2.1 and not TRELLIS.2

TRELLIS.2 4B produces higher-fidelity PBR-textured meshes from a single image
and is a strong candidate for a future enhancement. It is listed as secondary in
the catalog because its Windows prebuilt CUDA wheels target **Python 3.11 /
PyTorch 2.7–2.8 / CUDA 12.8** — the `visualbruno/ComfyUI-Trellis2` node pack
distributes these wheels pre-compiled. The reference setup runs **Python 3.12 /
PyTorch 2.10 / cu130** (Blackwell + SageAttention), which is incompatible with
those wheels; building from source would require a CUDA 12.8 toolchain separate
from the installed cu130 ComfyUI environment. In addition, TRELLIS.2 has a
**gated** dependency (`facebook/dinov3-vitl16-pretrain-lvd1689m`) that requires
accepting Meta's HF license and running `hf auth login` before the first
download.

Hunyuan3D 2.1 runs natively today: one `.safetensors` checkpoint, core ComfyUI
nodes only, no gated deps. When TRELLIS.2 wheel support catches up to the
reference Python/PyTorch/CUDA stack, it becomes a viable upgrade path for
textured output.

## Local-only and offline

The graph is ComfyUI core-native — no node pack, no external network calls
during inference. The checkpoint bundles everything (DiT + DINOv2 + VAE); no
auto-downloads on first run. Fully air-gappable after the initial model download.

## Performance (RTX 5090 / cu130 / SageAttention)

A typical run at `octree_resolution 256` completes in under two minutes on the
reference card (30 KSampler steps + voxel decode + mesh extraction). Model load
is the dominant cost in the first session; subsequent runs in the same session
skip the checkpoint load.
