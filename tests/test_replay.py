from __future__ import annotations
import pytest
from scripts.generate import _args_from_sidecar


def _video_sidecar():
    return {
        "schema": 2, "modality": "video", "mode": "i2v", "brand": "example-brand",
        "seed": 42, "model": "ltx-2.3-22b-dev-nvfp4.safetensors", "watermark": False,
        "prompt": "P", "negative": "N, anti-warp",
        "inputs": {"subject": "rolls forward", "from_image": "rover.png", "length": 97,
                   "fps": 25, "width": 768, "height": 512, "audio": True},
        "comfy_url": "http://127.0.0.1:8000", "timestamp": "2026-06-08T00:00:00",
    }


def _image_sidecar():
    return {
        "schema": 2, "modality": "image", "mode": "product", "brand": "example-brand",
        "seed": 7, "model": "z_image_bf16.safetensors", "watermark": True,
        "prompt": "P", "negative": "",
        "inputs": {"subject": "an armored rover", "variant": "base", "asset": "primary.png",
                   "model": "flux2_dev_fp8mixed.safetensors"},
        "comfy_url": "http://127.0.0.1:8000", "timestamp": "2026-06-08T00:00:00",
    }


def _threed_sidecar():
    return {
        "schema": 2, "modality": "3d", "mode": "image", "brand": "example-brand",
        "seed": 11, "model": "hunyuan_3d_v2.1.safetensors", "watermark": False,
        "prompt": "", "negative": "",
        "inputs": {"from_image": "rover.png", "octree": 256, "model": "hunyuan_3d_v2.1.safetensors",
                   "format": "stl"},
        "comfy_url": "http://127.0.0.1:8000", "timestamp": "2026-06-08T00:00:00", "format": "stl",
    }


def test_video_round_trip():
    a = _args_from_sidecar(_video_sidecar())
    assert a.modality == "video" and a.mode == "i2v" and a.brand == "example-brand"
    assert a.seed == 42
    assert a.from_image == "rover.png"
    assert a.length == 97 and a.fps == 25 and a.width == 768 and a.height == 512
    assert a.audio is True


def test_image_reconstructs_inputs():
    a = _args_from_sidecar(_image_sidecar())
    assert a.modality == "image" and a.mode == "product"
    assert a.subject == "an armored rover"
    assert a.variant == "base"
    assert a.asset == "primary.png"
    # the user's --model OVERRIDE (from inputs), NOT the top-level resolved model file
    assert a.model == "flux2_dev_fp8mixed.safetensors"


def test_image_upscale_round_trips():
    s = _image_sidecar()
    s["inputs"]["upscale"] = True
    s["inputs"]["upscale_model"] = "4x-UltraSharp.pth"
    a = _args_from_sidecar(s)
    assert a.upscale is True
    assert a.upscale_model == "4x-UltraSharp.pth"


def test_image_upscale_absent_defaults_false():
    # a non-upscaled image sidecar reconstructs to upscale=False
    a = _args_from_sidecar(_image_sidecar())
    assert a.upscale is False
    assert a.upscale_model is None


def test_video_upscale_round_trips():
    s = _video_sidecar()
    s["inputs"]["upscale"] = True
    s["inputs"]["upscale_model"] = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    a = _args_from_sidecar(s)
    assert a.upscale is True
    assert a.upscale_model == "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"


def test_3d_reconstructs_inputs():
    a = _args_from_sidecar(_threed_sidecar())
    assert a.modality == "3d" and a.mode == "image"
    assert a.from_image == "rover.png"
    assert a.octree == 256
    assert a.format == "stl"
    assert a.subject is None  # 3d has no subject input


def test_schema_gate_refuses_schema1():
    # schema absent -> defaults to 1; no inputs block -> cannot reconstruct
    bad = {"modality": "image", "mode": "txt2img", "brand": "b", "seed": 1}
    with pytest.raises(ValueError):
        _args_from_sidecar(bad)
    # explicit schema 1 also refused
    with pytest.raises(ValueError):
        _args_from_sidecar({**bad, "schema": 1})


def test_agent_run_sidecar_refused():
    # an auto_generate.py run sidecar carries schema 2 but kind="agent-run" and lacks
    # the inputs/model/negative a render sidecar has -> replay must refuse it cleanly.
    bad = {"schema": 2, "kind": "agent-run", "modality": "image", "mode": "agent",
           "brand": "example-brand", "subject": "an armored rover", "agent": True,
           "iterations": 2, "passed": True, "final_score": 0.97, "winning_seed": 7}
    with pytest.raises(ValueError):
        _args_from_sidecar(bad)


def test_seed_override():
    a = _args_from_sidecar(_video_sidecar(), seed=999)
    assert a.seed == 999
    # None keeps the recorded seed
    b = _args_from_sidecar(_video_sidecar(), seed=None)
    assert b.seed == 42


def test_comfy_url_fallback_and_override():
    # no override -> recorded comfy_url
    a = _args_from_sidecar(_video_sidecar(), comfy_url=None)
    assert a.comfy_url == "http://127.0.0.1:8000"
    # explicit override wins
    b = _args_from_sidecar(_video_sidecar(), comfy_url="http://10.0.0.5:9000")
    assert b.comfy_url == "http://10.0.0.5:9000"


def test_comfy_url_default_when_absent():
    s = _video_sidecar()
    del s["comfy_url"]
    a = _args_from_sidecar(s)
    assert a.comfy_url == "http://127.0.0.1:8000"


def test_comfy_output_dir_only_when_passed():
    a = _args_from_sidecar(_video_sidecar())
    assert a.comfy_output_dir is None
    b = _args_from_sidecar(_video_sidecar(), comfy_output_dir="/tmp/comfy")
    assert b.comfy_output_dir == "/tmp/comfy"


def test_watermark_reconstructed():
    assert _args_from_sidecar(_image_sidecar()).watermark is True
    assert _args_from_sidecar(_video_sidecar()).watermark is False


def test_audio_defaults_true_when_absent():
    # audio sidecars never store the video `audio` key; reconstruction must default it True
    s = _image_sidecar()
    a = _args_from_sidecar(s)
    assert a.audio is True


def test_reserved_run_attrs_present():
    # run() reads these even though replay never sets them from the sidecar
    a = _args_from_sidecar(_video_sidecar())
    assert a.out_name is None and a.timeout is None and a.free_before is None


def test_roundtrip_with_build_meta_video():
    # prove A1 (build_meta) <-> A2 (_args_from_sidecar) fit: produce a sidecar from a fake wf,
    # then reconstruct args and confirm the key inputs survive.
    from scripts.brandkit.sidecar import build_meta
    wf = {
        "1": {"_meta": {"title": "brand:positive"}, "inputs": {"text": "P"}},
        "2": {"_meta": {"title": "brand:negative"}, "inputs": {"text": "N, anti-warp"}},
    }
    inputs = {"subject": "rover rolls", "from_image": "rover.png", "length": 97,
              "fps": 25, "width": 768, "height": 512, "audio": False}
    meta = build_meta(modality="video", mode="i2v", brand="example-brand", seed=42,
                      model="ltx.safetensors", watermark=False, comfy_url="http://x",
                      wf=wf, inputs=inputs, timestamp="2026-06-08T00:00:00")
    a = _args_from_sidecar(meta)
    assert a.modality == "video" and a.mode == "i2v" and a.brand == "example-brand"
    assert a.seed == 42 and a.from_image == "rover.png"
    assert a.length == 97 and a.fps == 25 and a.width == 768 and a.height == 512
    assert a.audio is False  # falsy-but-meaningful survives the round trip


def test_roundtrip_with_build_meta_3d_format():
    from scripts.brandkit.sidecar import build_meta
    inputs = {"from_image": "rover.png", "octree": 256, "model": "h3d.safetensors", "format": "stl"}
    meta = build_meta(modality="3d", mode="image", brand="b", seed=11, model="h3d.safetensors",
                      watermark=False, comfy_url="http://x", wf={}, inputs=inputs,
                      timestamp="t", fmt="stl")
    a = _args_from_sidecar(meta)
    assert a.from_image == "rover.png" and a.octree == 256 and a.format == "stl"
    assert a.subject is None


# --- replay pins the recorded model + detects drift (P1, 2026-10-15) -----------------------------
# A brand pin or a Chimera default can change after a render; replay must not silently re-render
# with the new model or a changed prompt/template/setting.

def test_replay_pins_the_recorded_model_when_no_override_was_used():
    s = _video_sidecar()            # recorded model, no inputs.model
    assert _args_from_sidecar(s).model == "ltx-2.3-22b-dev-nvfp4.safetensors"


def test_replay_model_override_wins_over_the_record():
    assert _args_from_sidecar(_image_sidecar(), model="qwen_image_2.1_int8_convrot.safetensors").model \
        == "qwen_image_2.1_int8_convrot.safetensors"


def _drift_wf(text="a knight", width=1024, seed=1, prefix="b_txt2img", extra=False):
    wf = {"1": {"class_type": "CLIPTextEncode", "_meta": {"title": "brand:positive"},
                "inputs": {"text": text, "clip": ["2", 0]}},
          "2": {"class_type": "CLIPLoader", "_meta": {"title": "clip"}, "inputs": {"clip_name": "c.safetensors"}},
          "3": {"class_type": "EmptyLatentImage", "_meta": {"title": "brand:latent"},
                "inputs": {"width": width, "height": 768, "batch_size": 1}},
          "4": {"class_type": "KSampler", "_meta": {"title": "brand:sampler"},
                "inputs": {"seed": seed, "steps": 8, "positive": ["1", 0], "latent_image": ["3", 0]}},
          "5": {"class_type": "SaveImage", "_meta": {"title": "brand:save"},
                "inputs": {"filename_prefix": prefix, "images": ["4", 0]}}}
    if extra:
        wf["6"] = {"class_type": "ImageScaleBy", "_meta": {"title": "x"}, "inputs": {"scale_by": 2.0, "image": ["4", 0]}}
    return wf


def _drift_meta(wf, model="m.safetensors"):
    from scripts.brandkit.sidecar import build_meta
    return build_meta(modality="image", mode="txt2img", brand="b", seed=1, model=model, watermark=False,
                      comfy_url="http://x", wf=wf, inputs={"subject": "a knight"}, timestamp="t")


def _drift(meta, wf, model="m.safetensors", model_override=None):
    from scripts.brandkit.replay import replay_drift
    return replay_drift(meta, model=model, wf=wf, modality="image", mode="txt2img",
                        model_override=model_override)


def test_replay_drift_is_empty_when_the_render_reproduces():
    assert _drift(_drift_meta(_drift_wf()), _drift_wf()) == []


def test_replay_drift_ignores_a_new_seed_and_output_prefix():
    assert _drift(_drift_meta(_drift_wf()), _drift_wf(seed=99, prefix="b_txt2img_99")) == []


def test_replay_drift_reports_each_kind_of_change():
    meta = _drift_meta(_drift_wf())
    assert any("prompt changed" in d for d in _drift(meta, _drift_wf(text="a knight, neon noir")))
    assert any("render settings changed" in d for d in _drift(meta, _drift_wf(width=640)))
    assert any("graph structure changed" in d for d in _drift(meta, _drift_wf(extra=True)))
    assert _drift(meta, _drift_wf(), model="n.safetensors") == [
        "model: recorded m.safetensors, would now load n.safetensors"]


def test_replay_drift_with_a_model_override_only_checks_the_prompt():
    # a deliberate re-run on a newer model changes the model, graph and settings by design
    meta = _drift_meta(_drift_wf())
    assert _drift(meta, _drift_wf(width=640, extra=True), model="q.safetensors", model_override="q.safetensors") == []
    assert any("prompt changed" in d for d in _drift(meta, _drift_wf(text="changed"), model="q.safetensors",
                                                     model_override="q.safetensors"))


def test_replay_drift_on_an_older_sidecar_checks_what_it_recorded():
    meta = _drift_meta(_drift_wf())
    meta.pop("provenance")          # pre-provenance schema-2 sidecar: no structure/settings record
    assert _drift(meta, _drift_wf(width=640, extra=True)) == []


def test_a_wan_camera_render_replays_its_move_and_quality():
    s = _video_sidecar()
    s["model"] = "wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors"
    s["inputs"].update(camera="pan-left", quality="full", length=81, fps=16, audio=False)
    a = _args_from_sidecar(s)
    assert (a.camera, a.quality, a.model) == ("pan-left", "full", s["model"])
