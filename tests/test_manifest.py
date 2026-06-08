from pathlib import Path
import pytest
from scripts.brandkit.manifest import load_manifest, BrandManifest, ManifestError

FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_loads_core_fields():
    m = load_manifest(FIX)
    assert isinstance(m, BrandManifest)
    assert m.name == "Test Brand"
    assert m.defaults.width == 768 and m.defaults.steps == 12
    assert m.lora.file == "lora/test.safetensors" and m.lora.strength == 0.7
    assert m.logo.position == "bottom-right"

def test_defaults_when_blocks_missing(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("name: Minimal\nstyle: x\n")
    m = load_manifest(p)
    assert m.defaults.model == "flux2_dev_fp8mixed.safetensors"
    assert m.lora.file is None and m.ip_adapter.enabled is False
    assert m.negative == ""

def test_missing_name_raises(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("style: x\n")
    with pytest.raises(ManifestError):
        load_manifest(p)

def test_new_blocks_round_trip(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text(
        "name: B\n"
        "watermark: { enabled_default: true, position: top-left, scale: 0.1, margin: 0.03, opacity: 0.8 }\n"
        "video: { model: ltx.safetensors, length: 49, fps: 24, audio: false }\n"
        "audio: { music_model: ace.safetensors, foley: hunyuan }\n"
        "threed: { model: trellis2, format: obj }\n"
    )
    m = load_manifest(p)
    assert m.watermark.enabled_default is True and m.watermark.position == "top-left"
    assert m.video.length == 49 and m.video.audio is False
    assert m.audio.foley == "hunyuan"
    assert m.threed.format == "obj"

def test_new_blocks_default_when_absent(tmp_path):
    p = tmp_path / "b.yaml"; p.write_text("name: B\n")
    m = load_manifest(p)
    assert m.watermark.enabled_default is False
    assert m.video.fps == 25 and m.threed.format == "glb"

def test_unknown_key_warns(tmp_path, capsys):
    p = tmp_path / "b.yaml"; p.write_text("name: B\nwatermark: { positon: top-left }\n")  # typo
    load_manifest(p)
    err = capsys.readouterr().err
    assert "positon" in err and "watermark" in err

def test_video_block_actually_loads_not_just_defaults(tmp_path):
    # guards against a dataclass added but its _sub() line forgotten (silent all-defaults)
    p = tmp_path / "b.yaml"; p.write_text("name: B\nvideo: { fps: 99 }\n")
    assert load_manifest(p).video.fps == 99

def test_video_block_has_size_defaults_and_overrides(tmp_path):
    p = tmp_path / "b.yaml"; p.write_text("name: B\nvideo: { width: 960, height: 544 }\n")
    m = load_manifest(p)
    assert m.video.width == 960 and m.video.height == 544
    p2 = tmp_path / "b2.yaml"; p2.write_text("name: B\n")
    m2 = load_manifest(p2)
    assert m2.video.width == 768 and m2.video.height == 512

def test_audio_block_full_round_trip(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text(
        "name: B\n"
        "audio: { music_model: ace.safetensors, music_tags: 'dark sting', music_bpm: 90,\n"
        "         music_keyscale: 'A minor', music_duration: 6.0, foley: hunyuan,\n"
        "         foley_model: foley.safetensors, foley_negative: 'music, speech',\n"
        "         foley_cfg: 5.0, foley_steps: 40 }\n"
    )
    m = load_manifest(p)
    assert m.audio.music_model == "ace.safetensors" and m.audio.music_tags == "dark sting"
    assert m.audio.music_bpm == 90 and m.audio.music_keyscale == "A minor"
    assert m.audio.music_duration == 6.0
    assert m.audio.foley == "hunyuan" and m.audio.foley_model == "foley.safetensors"
    assert m.audio.foley_negative == "music, speech"
    assert m.audio.foley_cfg == 5.0 and m.audio.foley_steps == 40

def test_audio_block_defaults_when_absent(tmp_path):
    p = tmp_path / "b.yaml"; p.write_text("name: B\n")
    m = load_manifest(p)
    assert m.audio.music_model is None and m.audio.music_bpm == 100
    assert m.audio.music_tags == "" and m.audio.music_keyscale == "C minor"
    assert m.audio.music_duration == 8.0
    assert m.audio.foley == "hunyuan" and m.audio.foley_model is None
    assert m.audio.foley_cfg == 4.5 and m.audio.foley_steps == 50
    assert "music" in m.audio.foley_negative and "speech" in m.audio.foley_negative

def test_threed_block_full_round_trip(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("name: B\nthreed: { model: h3d.safetensors, format: obj, octree: 128, steps: 40, cfg: 6.0 }\n")
    m = load_manifest(p)
    assert m.threed.model == "h3d.safetensors" and m.threed.format == "obj"
    assert m.threed.octree == 128 and m.threed.steps == 40 and m.threed.cfg == 6.0

def test_threed_defaults(tmp_path):
    p = tmp_path / "b.yaml"; p.write_text("name: B\n")
    t = load_manifest(p).threed
    assert t.model is None and t.format == "glb" and t.octree == 256 and t.steps == 30 and t.cfg == 5.0
