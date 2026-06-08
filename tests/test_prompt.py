from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.prompt import build_prompt, build_audio_prompt
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_weaves_brand_into_prompt():
    m = load_manifest(FIX)
    pos, neg = build_prompt(m, "a coffee mug")
    assert "a coffee mug" in pos
    assert "clean studio look" in pos           # style
    assert "product render" in pos              # suffix
    assert "#101010" in pos or "101010" in pos  # palette described
    assert neg == "blurry, watermark"

def test_prefix_and_empty_palette(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text('name: B\nprompt_prefix: "logo of"\nstyle: "flat vector"\n')
    m = load_manifest(p)
    pos, neg = build_prompt(m, "a fox")
    assert pos.startswith("logo of")
    assert "a fox" in pos and "flat vector" in pos
    assert neg == ""


def test_audio_prompt_music_prepends_brand_tags():
    m = load_manifest(FIX)
    pos, neg = build_audio_prompt(m, "short logo sting", "music")
    assert pos == "dark cinematic, industrial percussion, short logo sting"
    assert neg == ""   # ACE-Step uses ConditioningZeroOut, no text negative


def test_audio_prompt_music_tags_only_when_no_subject():
    m = load_manifest(FIX)
    pos, _ = build_audio_prompt(m, "", "music")
    assert pos == "dark cinematic, industrial percussion"


def test_audio_prompt_foley_uses_subject_and_foley_negative():
    m = load_manifest(FIX)
    pos, neg = build_audio_prompt(m, "tracked rover on gravel, motor hum", "foley")
    assert pos == "tracked rover on gravel, motor hum"
    assert neg == "music, speech"
