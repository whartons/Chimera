from __future__ import annotations
from scripts.brandkit.sidecar import (
    SCHEMA_VERSION, graph_prompts, relevant_inputs, build_meta, graph_signature,
)


def _img_wf():
    # a built image/video graph carries the prompt text on titled nodes;
    # the video filler APPENDS anti-warp terms to the negative inside the graph.
    return {
        "1": {"_meta": {"title": "brand:positive"}, "inputs": {"text": "P"}},
        "2": {"_meta": {"title": "brand:negative"}, "inputs": {"text": "N, anti-warp"}},
    }


def test_graph_prompts_image_reads_back_text():
    assert graph_prompts(_img_wf(), "image", "txt2img") == ("P", "N, anti-warp")


def test_graph_prompts_video_captures_appended_negative():
    # the key regression: the filler-appended video negative must reach the sidecar
    assert graph_prompts(_img_wf(), "video", "i2v") == ("P", "N, anti-warp")


def test_graph_prompts_audio_music_reads_tags():
    wf = {"7": {"_meta": {"title": "brand:tags"}, "inputs": {"tags": "warm pad"}}}
    assert graph_prompts(wf, "audio", "music") == ("warm pad", "")


def test_graph_prompts_audio_foley_reads_prompt_and_negative():
    wf = {"3": {"_meta": {"title": "brand:foley"},
                "inputs": {"prompt": "footsteps", "negative_prompt": "music"}}}
    assert graph_prompts(wf, "audio", "foley") == ("footsteps", "music")


def test_graph_prompts_3d_returns_empty():
    assert graph_prompts({"1": {"_meta": {"title": "x"}, "inputs": {}}}, "3d", "image") == ("", "")


def test_graph_prompts_missing_node_degrades_to_empty():
    assert graph_prompts({}, "image", "txt2img") == ("", "")


def test_graph_prompts_missing_input_degrades_to_empty():
    # node present but the expected input key is absent
    wf = {"1": {"_meta": {"title": "brand:positive"}, "inputs": {}}}
    assert graph_prompts(wf, "image", "txt2img") == ("", "")


def test_relevant_inputs_keeps_only_modality_keys_and_drops_none():
    flat = {"subject": "rover", "asset": None, "variant": "turbo", "model": None,
            "from_image": "x.png", "length": 97}  # from_image/length not image keys
    out = relevant_inputs("image", "txt2img", flat)
    assert out == {"subject": "rover", "variant": "turbo"}


def test_relevant_inputs_image_keeps_upscale_when_set_drops_when_none():
    # on render: upscale True + resolved model survive; off render: both None -> dropped,
    # so off-by-default image sidecars never gain an `upscale` key.
    on = relevant_inputs("image", "txt2img",
                         {"subject": "rover", "upscale": True, "upscale_model": "4x-UltraSharp.pth"})
    assert on["upscale"] is True and on["upscale_model"] == "4x-UltraSharp.pth"
    off = relevant_inputs("image", "txt2img",
                          {"subject": "rover", "upscale": None, "upscale_model": None})
    assert "upscale" not in off and "upscale_model" not in off


def test_relevant_inputs_keeps_false_and_zero():
    flat = {"subject": "clip", "from_image": "x.png", "length": 0, "fps": 25,
            "width": 768, "height": 512, "audio": False}
    out = relevant_inputs("video", "i2v", flat)
    # audio=False and length=0 are meaningful and must survive
    assert out["audio"] is False
    assert out["length"] == 0
    assert "subject" in out and "from_image" in out


def test_relevant_inputs_audio_selects_by_mode():
    flat = {"subject": "s", "duration": 5.0, "bpm": 120, "keyscale": "C major",
            "from_video": "v.mp4", "fps": 25}
    music = relevant_inputs("audio", "music", flat)
    assert set(music) == {"subject", "duration", "bpm", "keyscale"}
    foley = relevant_inputs("audio", "foley", flat)
    assert set(foley) == {"subject", "from_video", "duration", "fps"}


def test_relevant_inputs_3d_keys():
    flat = {"from_image": "x.png", "octree": 256, "model": "h3d.safetensors",
            "format": "stl", "subject": "ignored"}
    out = relevant_inputs("3d", "image", flat)
    assert set(out) == {"from_image", "octree", "model", "format"}


def test_build_meta_schema_and_readback():
    meta = build_meta(
        modality="video", mode="i2v", brand="example-brand", seed=7,
        model="ltx.safetensors", watermark=False, comfy_url="http://x",
        wf=_img_wf(), inputs={"subject": "rover", "from_image": "r.png", "audio": False},
        timestamp="2026-06-08T00:00:00",
    )
    assert meta["schema"] == SCHEMA_VERSION
    assert meta["prompt"] == "P" and meta["negative"] == "N, anti-warp"
    assert meta["modality"] == "video" and meta["mode"] == "i2v"
    assert meta["brand"] == "example-brand" and meta["seed"] == 7
    assert meta["model"] == "ltx.safetensors" and meta["watermark"] is False
    assert meta["comfy_url"] == "http://x" and meta["timestamp"] == "2026-06-08T00:00:00"
    assert meta["inputs"] == {"subject": "rover", "from_image": "r.png", "audio": False}
    assert "format" not in meta  # fmt not passed


def test_build_meta_includes_format_when_passed():
    meta = build_meta(
        modality="3d", mode="image", brand="b", seed=1, model="h3d.safetensors",
        watermark=False, comfy_url="http://x", wf={},
        inputs={"from_image": "x.png", "format": "stl"}, timestamp="t", fmt="stl",
    )
    assert meta["format"] == "stl"
    assert meta["prompt"] == "" and meta["negative"] == ""
    assert meta["inputs"] == {"from_image": "x.png", "format": "stl"}


def test_generate_collects_superset_of_all_input_keys():
    # Drift guard: generate.py harvests SIDECAR_INPUT_KEYS into the `inputs` dict, then
    # sidecar.relevant_inputs keeps the modality subset. If someone adds a key to a
    # _INPUT_KEYS tuple but not to generate.py's harvest list, relevant_inputs would
    # silently drop it. Assert the harvest list covers every _INPUT_KEYS value except
    # "format", which generate.py injects separately as the resolved fmt.
    from scripts.generate import SIDECAR_INPUT_KEYS
    from scripts.brandkit.sidecar import _INPUT_KEYS
    needed = {k for keys in _INPUT_KEYS.values() for k in keys} - {"format"}
    assert needed <= set(SIDECAR_INPUT_KEYS), needed - set(SIDECAR_INPUT_KEYS)


def test_graph_signature_stable_across_scalar_changes():
    # the signature fingerprints STRUCTURE — same nodes/edges with different seed/prompt -> same hash
    a = {"1": {"class_type": "X", "_meta": {"title": "brand:positive"},
               "inputs": {"text": "P", "model": ["2", 0]}},
         "2": {"class_type": "Y", "inputs": {"seed": 1}}}
    b = {"1": {"class_type": "X", "_meta": {"title": "brand:positive"},
               "inputs": {"text": "TOTALLY DIFFERENT", "model": ["2", 0]}},
         "2": {"class_type": "Y", "inputs": {"seed": 9999}}}
    assert graph_signature(a) == graph_signature(b)


def test_graph_signature_changes_on_structure():
    a = {"1": {"class_type": "X", "inputs": {"model": ["2", 0]}}, "2": {"class_type": "Y", "inputs": {}}}
    retargeted = {"1": {"class_type": "X", "inputs": {"model": ["3", 0]}},
                  "2": {"class_type": "Y", "inputs": {}}}   # edge points elsewhere
    reclassed = {"1": {"class_type": "Z", "inputs": {"model": ["2", 0]}},
                 "2": {"class_type": "Y", "inputs": {}}}    # node class changed
    assert graph_signature(a) != graph_signature(retargeted)
    assert graph_signature(a) != graph_signature(reclassed)


def test_graph_signature_empty_graph():
    assert graph_signature({}) == ""


def test_build_meta_provenance_graph_signature_always_present():
    meta = build_meta(modality="image", mode="txt2img", brand="b", seed=1, model="m", watermark=False,
                      comfy_url="http://x", wf=_img_wf(), inputs={"subject": "s"}, timestamp="t")
    assert meta["provenance"]["graph_signature"]            # always recorded
    assert "comfyui_version" not in meta["provenance"]      # not supplied -> omitted
    assert "pipeline_git_sha" not in meta["provenance"]


def test_build_meta_provenance_includes_version_and_sha_when_given():
    meta = build_meta(modality="image", mode="txt2img", brand="b", seed=1, model="m", watermark=False,
                      comfy_url="http://x", wf=_img_wf(), inputs={"subject": "s"}, timestamp="t",
                      comfyui_version="v0.24.1", pipeline_git_sha="abc1234-dirty")
    p = meta["provenance"]
    assert p["comfyui_version"] == "v0.24.1" and p["pipeline_git_sha"] == "abc1234-dirty"
    assert p["graph_signature"]  # still present alongside


def test_graph_prompts_zimage_empty_negative_contract():
    # Z-Image zeroes the negative conditioning instead of writing brand:negative.text,
    # so the negative node has a `conditioning` input but NO `text` key -> the sidecar
    # legitimately records negative "". Pin this so a refactor can't silently regress it.
    wf = {
        "1": {"_meta": {"title": "brand:positive"}, "inputs": {"text": "P"}},
        "2": {"_meta": {"title": "brand:negative"}, "inputs": {"conditioning": [["5", 0]]}},
    }
    assert graph_prompts(wf, "image", "txt2img") == ("P", "")
