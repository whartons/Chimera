from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.audio import build
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_music_fills_tags_seed_duration_bpm_keyscale():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="dark sting, instrumental", negative="", seed=7,
               mode="music", duration=6.0, bpm=120, keyscale="A minor")
    enc = find_node_by_title(wf, "brand:tags")[1]["inputs"]
    assert enc["tags"] == "dark sting, instrumental"
    assert enc["seed"] == 7 and enc["duration"] == 6.0 and enc["bpm"] == 120
    assert enc["keyscale"] == "A minor"
    assert find_node_by_title(wf, "brand:sampler")[1]["inputs"]["seed"] == 7
    assert find_node_by_title(wf, "brand:latent")[1]["inputs"]["seconds"] == 6.0

def test_music_uses_manifest_and_default_model_when_unset():
    m = load_manifest(FIX)  # fixture sets no music_model, music_bpm=90
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="music")
    enc = find_node_by_title(wf, "brand:tags")[1]["inputs"]
    assert enc["bpm"] == 90 and enc["duration"] == 8.0  # manifest bpm, default duration
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == \
        "acestep_v1.5_xl_turbo_bf16.safetensors"  # DEFAULT_MUSIC_MODEL

def test_music_model_override_from_arg():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="music", model="other.safetensors")
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == "other.safetensors"

def test_foley_fills_video_prompt_negative_framerate_duration_seed():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="rover on gravel, motor hum", negative="music, speech",
               seed=42, mode="foley", from_video="src.mp4", frame_rate=25.0, duration=3.88,
               fps=25.0)
    f = find_node_by_title(wf, "brand:foley")[1]["inputs"]
    assert f["prompt"] == "rover on gravel, motor hum"
    assert f["negative_prompt"] == "music, speech"
    assert f["frame_rate"] == 25.0 and f["duration"] == 3.88 and f["seed"] == 42
    assert f["cfg_scale"] == 4.5 and f["steps"] == 50          # manifest defaults
    assert find_node_by_title(wf, "brand:load_video")[1]["inputs"]["file"] == "src.mp4"
    assert find_node_by_title(wf, "brand:create_video")[1]["inputs"]["fps"] == 25.0

def test_foley_falls_back_to_manifest_foley_negative_when_blank():
    m = load_manifest(FIX)  # fixture foley_negative = "music, speech"
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="foley",
               from_video="s.mp4", frame_rate=24.0, duration=2.0, fps=24.0)
    assert find_node_by_title(wf, "brand:foley")[1]["inputs"]["negative_prompt"] == "music, speech"

def test_foley_model_override_from_arg():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="foley", from_video="s.mp4",
               frame_rate=24.0, duration=2.0, fps=24.0, model="myfoley.safetensors")
    assert find_node_by_title(wf, "brand:foley_model")[1]["inputs"]["model_name"] == "myfoley.safetensors"

def test_foley_requires_from_video():
    import pytest
    m = load_manifest(FIX)
    with pytest.raises(ValueError):
        build(ROOT, m, positive="x", negative="", seed=1, mode="foley")

def test_foley_watermark_injected_over_components_keeps_audio():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="music", seed=1, mode="foley", watermark=True,
               from_video="s.mp4", frame_rate=25.0, duration=3.0, fps=25.0,
               watermark_logo="primary.png", logo_px=(120, 120), width=768, height=512)
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    foley_id, _ = find_node_by_title(wf, "brand:foley")
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert cv["images"] == [cid, 0] and cv["audio"] == [foley_id, 0]
