"""--free-before defaults: FLUX.2 image jobs free ComfyUI's VRAM first (GPU-free)."""
import argparse

import scripts.generate as G
from scripts.brandkit.manifest import default_manifest
from scripts.brandkit.workflow import needs_free_before


def _ns(**kw):
    base = {"modality": "image", "mode": "txt2img", "variant": None, "model": None}
    base.update(kw)
    return argparse.Namespace(**base)


def test_flux2_graphs_need_free_before():
    # FLUX.2 loads a ~33 GB bf16 text encoder; on ComfyUI 0.40 (comfy-aimdo 0.5.6) that disk-streamed
    # load fails with Windows error 1450 while other models are staged, and succeeds after /free
    # (2026-10-14 smoke). Relight always loads FLUX.2, even on a Z-Image brand.
    assert needs_free_before("relight", None, "z_image_turbo_nvfp4.safetensors")
    assert needs_free_before("txt2img", None, "flux2-dev-nvfp4-mixed.safetensors")
    assert not needs_free_before("txt2img", None, "z_image_turbo_nvfp4.safetensors")
    assert not needs_free_before("product", "base", "z_image_bf16.safetensors")


def test_default_free_before_policy_per_job():
    m = default_manifest()
    assert G._default_free_before(_ns(mode="relight"), m) is True
    assert G._default_free_before(_ns(model="flux2_dev_fp8mixed.safetensors"), m) is True
    assert G._default_free_before(_ns(model="z_image_turbo_nvfp4.safetensors"), m) is False
    for modality in ("video", "audio", "3d"):   # unchanged: heavy modalities always free first
        assert G._default_free_before(_ns(modality=modality), m) is True


def test_default_free_before_follows_brand_default_model():
    m = default_manifest()
    m.defaults.model = "flux2-dev-nvfp4-mixed.safetensors"   # a FLUX.2 brand, no --model given
    assert G._default_free_before(_ns(), m) is True
