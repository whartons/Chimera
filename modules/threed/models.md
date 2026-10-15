# 3D module — models

Three models. Filenames must match what is in the template JSON (or edit the template to match what you
downloaded). No machine-absolute paths — all destinations are relative to your `ComfyUI/` root. No custom
node pack is required for any of them.

---

## TRELLIS.2 (default) and Pixal3D — textured, ComfyUI ≥ 0.40

One graph ([`brand-3d-trellis2.json`](../../workflows/templates/brand-3d-trellis2.json)) serves both. Its
nodes (`Trellis2*`, `Pixal3DConditioning`, `MoGe*`, `RemoveBackground`, `UnwrapMesh`, `Bake*`,
`ApplyTextureToMesh`, `Save3DAdvanced`, …) are core in ComfyUI 0.40. The weights are the Comfy-Org int8
"convrot" builds; nothing is gated (the old `facebook/dinov3` login is not needed).

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License | Needed by |
|------|-----------------|----------------------------------|------|---------|-----------|
| `trellis_2_int8_convrot.safetensors` | `Comfy-Org/TRELLIS.2` | `diffusion_models/` | ~4.9 GB | ✅ MIT | TRELLIS.2 |
| `pixal3d_int8_convrot.safetensors` | `Comfy-Org/Pixal3D` | `diffusion_models/` | ~5.2 GB | ✅ MIT | Pixal3D |
| `trellis_2_shape_vae_bf16.safetensors` | `Comfy-Org/Pixal3D` | `vae/` | ~1.0 GB | ✅ MIT | both |
| `trellis_2_texture_vae_bf16.safetensors` | `Comfy-Org/Pixal3D` | `vae/` | ~0.9 GB | ✅ MIT | both |
| `dino_v3_L_naf_fp32.safetensors` | `Comfy-Org/Pixal3D` | `clip_vision/` | ~1.1 GB | ⚠️ repo lists MIT; upstream DINOv3 is under Meta's DINOv3 license | both |
| `birefnet.safetensors` | `Comfy-Org/BiRefNet` | `background_removal/` | ~0.4 GB | ✅ MIT | both |
| `moge_2_vitl_normal_fp16.safetensors` | `Comfy-Org/MoGe` | `geometry_estimation/` | ~0.6 GB | ✅ MIT | Pixal3D |

---

## Hunyuan3D 2.1 — fast, shape only

One checkpoint, one destination: drop it into `ComfyUI/models/checkpoints/`. All nodes used
(`ImageOnlyCheckpointLoader`, `ModelSamplingAuraFlow`, `CLIPVisionEncode`, `Hunyuan3Dv2Conditioning`,
`EmptyLatentHunyuan3Dv2`, `KSampler`, `VAEDecodeHunyuan3D`, `VoxelToMesh`, `SaveGLB`) ship with ComfyUI
0.22.3.

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
