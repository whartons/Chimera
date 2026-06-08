# 3D module — models

One checkpoint, one destination. Download the file and drop it into
`ComfyUI/models/checkpoints/`. The filename must match what is in the template
JSON (or edit the template to match what you downloaded). No machine-absolute
paths — all destinations are relative to your `ComfyUI/` root.

No custom node pack is required. All nodes used (`ImageOnlyCheckpointLoader`,
`ModelSamplingAuraFlow`, `CLIPVisionEncode`, `Hunyuan3Dv2Conditioning`,
`EmptyLatentHunyuan3Dv2`, `KSampler`, `VAEDecodeHunyuan3D`, `VoxelToMesh`,
`SaveGLB`) ship with ComfyUI 0.22.3.

---

## Hunyuan3D 2.1

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `hunyuan_3d_v2.1.safetensors` | `Comfy-Org/hunyuan3D_2.1_repackaged` | `checkpoints/` | ~7.4 GB | ⚠️ see note |

### What this file bundles

`hunyuan_3d_v2.1.safetensors` is a single-file repack that combines three
components, all loaded together by `ImageOnlyCheckpointLoader`:

- **DiT shape model** (output slot 0) — the 3D diffusion transformer that
  generates the latent shape representation. Wrapped by `ModelSamplingAuraFlow`
  and driven by `KSampler`.
- **DINOv2 CLIP-Vision encoder** (output slot 1) — encodes the input image into
  the conditioning signal consumed by `CLIPVisionEncode` + `Hunyuan3Dv2Conditioning`.
  DINOv2 is **ungated** — no Hugging Face token or license acceptance required.
- **3D VAE** (output slot 2) — decodes the latent into a voxel field via
  `VAEDecodeHunyuan3D`, which is then converted to a triangle mesh by
  `VoxelToMesh`.

### No gated dependencies

None of the components in this checkpoint require a Hugging Face account,
token, or license acceptance step. Download is a single `huggingface-cli download`
or browser download from the `Comfy-Org/hunyuan3D_2.1_repackaged` repo.

### License note

Hunyuan3D 2.1 is distributed under a Tencent community license. Personal,
non-commercial use is not restricted. **Verify terms before any commercial
distribution** — recorded here as neutral reference for anyone who forks.
License text is in the `Comfy-Org/hunyuan3D_2.1_repackaged` repository.

---

## Caveats

- **Shape only (no PBR texture):** the native pipeline produces geometry
  (POSITION + indices) with no materials, textures, or vertex colors. The output
  GLB is a valid glTF-v2 file but will appear as an untextured grey mesh in most
  viewers. Downstream texturing (Blender, Substance Painter, etc.) works normally
  on the exported geometry. See the README for the PBR future-enhancement note.
- **Single file, no splits:** unlike the ACE-Step audio stack, this is a
  monolithic checkpoint — one file covers the full pipeline.
- **`checkpoints/` destination:** `ImageOnlyCheckpointLoader` targets
  `models/checkpoints/`, the standard ComfyUI checkpoint folder. Do not place it
  in `diffusion_models/` or `unet/`.
