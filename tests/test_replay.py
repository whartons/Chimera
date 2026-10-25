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
    with pytest.raises(ValueError, match="agent-run"):   # refused as what it is, not by its mode
        _args_from_sidecar(bad)


def test_seed_override():
    a = _args_from_sidecar(_video_sidecar(), seed=999)
    assert a.seed == 999
    # None keeps the recorded seed
    b = _args_from_sidecar(_video_sidecar(), seed=None)
    assert b.seed == 42


def test_comfy_url_fallback_and_override():
    # no override -> the local default, never the sidecar's recorded URL (sidecars get shared)
    s = _video_sidecar()
    s["comfy_url"] = "http://attacker.invalid:8000"
    a = _args_from_sidecar(s, comfy_url=None)
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



# --- 2026-10 review: --model, cross-family replays, and sidecars as untrusted input ------------------
def _neg_wf(neg="brand negative", width=1024):
    wf = _drift_wf(width=width)
    wf["7"] = {"class_type": "CLIPTextEncode", "_meta": {"title": "brand:negative"},
               "inputs": {"text": neg, "clip": ["2", 0]}}
    return wf


def test_a_cross_family_model_override_does_not_compare_the_negative():
    # each family builds its own negative (Z-Image none, LTX/Wan their own lists): every cross-family
    # `replay --model` stopped on a false "negative changed"
    meta = _drift_meta(_neg_wf(neg=""), model="z_image_turbo_nvfp4.safetensors")
    assert _drift(meta, _neg_wf(), model="q.safetensors", model_override="q.safetensors") == []


def test_an_override_naming_the_recorded_model_keeps_every_check():
    meta = _drift_meta(_neg_wf(), model="q.safetensors")
    drift = _drift(meta, _neg_wf(neg="changed", width=640), model="q.safetensors", model_override="q.safetensors")
    assert any("negative changed" in d for d in drift) and any("render settings" in d for d in drift)


def _wan_sidecar():
    s = _video_sidecar()
    s["model"] = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
    s["inputs"].update(length=81, fps=16, audio=False, quality="full")
    return s


def test_a_cross_family_video_replay_drops_the_old_familys_clip_settings():
    s = _video_sidecar()                                    # LTX: 97 frames at 25 fps with audio, upscaled
    s["inputs"].update(upscale=True, upscale_model="ltx-2.3-spatial-upscaler-x2-1.1.safetensors")
    a = _args_from_sidecar(s, model="wan22")
    assert (a.length, a.fps, a.audio, a.quality, a.camera, a.upscale, a.upscale_model) == \
        (None, None, None, None, None, False, None)
    assert (a.width, a.height) == (768, 512)                # the framing carries over
    b = _args_from_sidecar(_wan_sidecar(), model="ltx23")
    assert (b.length, b.fps, b.audio, b.quality) == (None, None, None, None)


def test_a_same_family_video_override_keeps_the_recorded_clip():
    a = _args_from_sidecar(_wan_sidecar(), model="wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors")
    assert (a.length, a.fps, a.quality) == (81, 16, "full")


def test_cross_family_image_and_3d_overrides_drop_family_only_inputs():
    assert _args_from_sidecar(_image_sidecar(), model="qwen_image_2.1_int8_convrot.safetensors").variant is None
    assert _args_from_sidecar(_image_sidecar(), model="z_image_turbo_nvfp4.safetensors").variant == "base"
    assert _args_from_sidecar(_threed_sidecar(), model="trellis2").octree is None
    assert _args_from_sidecar(_threed_sidecar(), model="hunyuan21").octree == 256


@pytest.mark.parametrize("brand", ["../..", "a/b", "..", ".hidden", "a\\b", "c:x", "trailing.", " pad"])
def test_replay_refuses_a_brand_that_is_not_a_folder_name(brand):
    s = _image_sidecar(); s["brand"] = brand
    with pytest.raises(ValueError, match="brand"):
        _args_from_sidecar(s)


@pytest.mark.parametrize("brand", ["my brand", "Café & Co", "acme.co"])
def test_replay_accepts_every_brand_new_brand_can_create(brand, tmp_path):
    # replay's brand check used to be stricter than new-brand's, so a brand with a space couldn't replay
    from scripts.brandkit.scaffold import new_brand
    (tmp_path / "brands" / "_template").mkdir(parents=True)
    (tmp_path / "brands" / "_template" / "brand.yaml").write_text('name: "x"\n', encoding="utf-8")
    new_brand(tmp_path, brand)
    s = _image_sidecar(); s["brand"] = brand
    assert _args_from_sidecar(s).brand == brand


@pytest.mark.parametrize("field, value, match", [
    ("modality", "cad", "modality"), ("mode", "../../../../evil", "mode"), ("mode", "C:\\evil", "mode"),
    ("seed", "1/../../evil", "seed"), ("seed", True, "seed"), ("seed", None, "seed")])
def test_replay_refuses_a_mode_seed_or_modality_that_could_name_a_folder(field, value, match):
    # the mode and seed name the output file: a crafted '../..' mode wrote a render outside outputs/ (2026-10)
    s = _image_sidecar(); s[field] = value
    with pytest.raises(ValueError, match=match):
        _args_from_sidecar(s)
    assert _args_from_sidecar({**_image_sidecar(), "seed": "bad"}, seed=5).seed == 5   # an override is fine


@pytest.mark.parametrize("key, value", [("asset", ".env"), ("from_image", "notes.txt"), ("from_video", "clip.png"),
                                        ("from_image", "id_rsa")])
def test_replay_only_uploads_media_files(key, value):
    # replay uploads the inputs to ComfyUI: a crafted sidecar naming '.env' would have sent that file
    s = _image_sidecar(); s.setdefault("inputs", {})[key] = value
    with pytest.raises(ValueError, match="isn't an? (image|video) file"):
        _args_from_sidecar(s)


def test_replay_modes_match_the_cli():
    from scripts import generate
    import argparse
    seen = {}
    real = argparse.ArgumentParser.parse_args
    try:
        def grab(self, *a, **k):
            for action in self._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        mode = next((x for x in sub._actions if x.dest == "mode"), None)
                        if mode is not None and mode.choices:
                            seen[name] = tuple(mode.choices)
            raise SystemExit(0)
        argparse.ArgumentParser.parse_args = grab
        with pytest.raises(SystemExit):
            generate.main()
    finally:
        argparse.ArgumentParser.parse_args = real
    from scripts.brandkit.replay import REPLAY_MODES
    assert {k: tuple(v) for k, v in REPLAY_MODES.items()} == {k: seen[k] for k in REPLAY_MODES}


@pytest.mark.parametrize("key, value", [("asset", "C:\\Users\\x\\secret.png"), ("from_image", "/home/x/id_rsa"),
                                        ("from_image", "../../notes.txt"), ("from_video", "a\\..\\..\\b.mp4")])
def test_replay_refuses_an_absolute_or_climbing_input_path(key, value):
    # a crafted sidecar uploaded any local file this way (2026-10 audit)
    s = _image_sidecar(); s["inputs"][key] = value
    with pytest.raises(ValueError, match="plain relative file name"):
        _args_from_sidecar(s)


def test_replay_takes_plain_relative_names():
    s = _image_sidecar(); s["inputs"]["asset"] = "sub/primary.png"
    assert _args_from_sidecar(s).asset == "sub/primary.png"



def test_replay_refuses_an_inputs_block_that_is_not_a_mapping():
    s = _image_sidecar()
    s["inputs"] = ["primary.png"]
    with pytest.raises(ValueError, match="mapping"):
        _args_from_sidecar(s)



# --- 2026-10 third review -----------------------------------------------------------------------------
import re  # noqa: E402

import scripts.brandkit.replay as R  # noqa: E402

ACE = "acestep_v1.5_xl_turbo_bf16.safetensors"
SA3 = "stable_audio_3_medium.safetensors"


def _sc(**over):
    d = {"schema": 2, "modality": "image", "mode": "txt2img", "brand": None, "seed": 7,
         "model": "qwen_image_2.1_int8.safetensors", "inputs": {"subject": "a rover"}}
    d.update(over)
    return d


@pytest.mark.parametrize("name", ["logo.gif", "ref.jfif", "ref.avif", "photo.HEIC"])
def test_replay_takes_the_image_inputs_generate_took(name):
    R.args_from_sidecar(_sc(mode="product", inputs={"subject": "a rover", "asset": name}))


@pytest.mark.parametrize("name", ["clip.m4v", "clip.mpg", "clip.wmv"])
def test_replay_takes_the_video_inputs_generate_took(name):
    R.args_from_sidecar(_sc(modality="audio", mode="foley", inputs={"subject": "steps", "from_video": name}))


@pytest.mark.parametrize("over, msg", [
    ({"schema": "2"}, "schema '2' isn't a number"),
    ({"inputs": {"subject": 7}}, "inputs.subject 7 isn't text"),
    ({"inputs": {}}, "records no inputs.subject"),
    ({"inputs": {"subject": "x", "duration": "8"}}, "inputs.duration '8' isn't a number"),
    ({"inputs": {"subject": "x", "length": True}}, "inputs.length True isn't a number"),
    ({"model": ["x"]}, "isn't a file name"),
    ({"modality": "3d", "mode": "image", "inputs": {"from_image": "r.png", "format": "fbx"}}, "format 'fbx'"),
])
def test_a_damaged_sidecar_is_refused_with_the_field_named(over, msg):
    # these crashed mid-render (or after a whole 3D render, for 'fbx') instead of "cannot replay"
    with pytest.raises(ValueError, match=re.escape(msg)):
        R.args_from_sidecar(_sc(**over))


def test_a_sidecar_without_a_brand_field_says_so():
    d = _sc()
    del d["brand"]
    with pytest.raises(ValueError, match="no brand field"):
        R.args_from_sidecar(d)


def test_cross_family_music_replay_compares_the_words_not_the_bpm_and_key(monkeypatch):
    # Stable Audio 3 appends explicit BPM/key to its brief (ACE-Step takes them as settings): "prompt changed"
    monkeypatch.setattr(R, "graph_prompts", lambda wf, mo, md: ("a heroic sting, 120 BPM, in E minor", ""))
    ace = {"model": ACE, "prompt": "a heroic sting", "inputs": {"bpm": 120, "keyscale": "E minor"}}
    assert R.replay_drift(ace, model=SA3, wf={}, modality="audio", mode="music", model_override="sa3") == []
    monkeypatch.setattr(R, "graph_prompts", lambda wf, mo, md: ("a heroic sting", ""))
    sa3 = {**ace, "model": SA3, "prompt": "a heroic sting, 120 BPM, in E minor"}
    assert R.replay_drift(sa3, model=ACE, wf={}, modality="audio", mode="music", model_override="acestep") == []
    monkeypatch.setattr(R, "graph_prompts", lambda wf, mo, md: ("a sad sting", ""))
    assert R.replay_drift(sa3, model=ACE, wf={}, modality="audio", mode="music", model_override="acestep")


def test_an_acestep_sidecar_from_before_v060_reports_the_shift_change(monkeypatch):
    monkeypatch.setattr(R, "graph_prompts", lambda wf, mo, md: ("a song", ""))
    monkeypatch.setattr(R, "graph_values", lambda wf, mo, md: "v1")
    old = {"model": ACE, "prompt": "a song", "negative": ""}          # no settings record: made before v0.6.0
    assert any("1.73" in d for d in R.replay_drift(old, model=ACE, wf={}, modality="audio", mode="music"))
    new = {**old, "provenance": {"graph_values": "v1"}}               # v0.6.0+ records (and checks) the settings
    assert R.replay_drift(new, model=ACE, wf={}, modality="audio", mode="music") == []
    assert R.replay_drift({**old, "model": SA3}, model=SA3, wf={}, modality="audio", mode="music") == []


def test_replay_notes_say_what_an_old_sidecar_cannot_check():
    assert R.replay_notes({"provenance": {"graph_values": "abc"}}) == []
    assert "the model and prompts" in R.replay_notes({})[0]
    assert "graph structure" in R.replay_notes({"provenance": {"graph_signature": "x"}})[0]


def test_an_agent_run_sidecar_is_refused_as_such():
    with pytest.raises(ValueError, match="agent-run"):
        R.args_from_sidecar({"schema": 2, "kind": "agent-run", "modality": "image", "mode": "agent", "brand": "b",
                             "seed": 1})


def test_cross_family_music_replay_with_no_recorded_prompt_or_an_empty_brief(monkeypatch):
    monkeypatch.setattr(R, "graph_prompts", lambda wf, mo, md: ("120 BPM", ""))
    rec = {"model": ACE, "inputs": {"bpm": 120}}                       # no prompt recorded: nothing to compare
    assert R.replay_drift(rec, model=SA3, wf={}, modality="audio", mode="music", model_override="sa3") == []
    rec["prompt"] = ""                                                  # an empty brief: SA3's is the BPM alone
    assert R.replay_drift(rec, model=SA3, wf={}, modality="audio", mode="music", model_override="sa3") == []


# --- 2026-10-25 review -------------------------------------------------------------------------------------
@pytest.mark.parametrize("modality, mode", [("audio", "music"), ("image", "txt2img")])
def test_a_render_with_an_empty_subject_replays(modality, mode):
    # `audio --brand B --subject ""` is a valid render (the brand's music_tags carry the brief), and replay refused it
    a = R.args_from_sidecar(_sc(modality=modality, mode=mode, brand="b", inputs={"subject": ""}))
    assert a.subject == ""


def test_a_sidecar_with_a_null_subject_is_still_refused():
    with pytest.raises(ValueError, match="records no inputs.subject"):
        R.args_from_sidecar(_sc(inputs={"subject": None}))
