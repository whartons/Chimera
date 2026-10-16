"""Audio: Stable Audio 3 Medium is the default music model (it won the 2026-10 listening comparison) and
powers the new `sfx` mode; ACE-Step 1.5 stays available (`model="acestep"`, e.g. for songs with vocals)."""
from pathlib import Path
import pytest
from scripts.brandkit import audio
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.nodes import find_node_by_title
from scripts.brandkit.prompt import build_audio_prompt
from scripts.brandkit.sidecar import graph_prompts, graph_values

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"


def _in(wf, title):
    return find_node_by_title(wf, title)[1]["inputs"]


def _build(mode="music", **kw):
    return audio.build(ROOT, load_manifest(FIX), positive="a synthwave stream intro", seed=21, mode=mode, **kw)


def test_stable_audio_3_is_the_default_music_model():
    m = load_manifest(FIX)
    assert audio.resolved_model(m, "music") == audio.SA3_MODEL == "stable_audio_3_medium.safetensors"
    wf = _build(duration=30)
    assert _in(wf, "brand:ckpt")["ckpt_name"] == audio.SA3_MODEL
    assert _in(wf, "brand:prompt")["value"] == "a synthwave stream intro"
    assert _in(wf, "brand:mode")["choice"] == "Music"
    assert _in(wf, "brand:latent")["seconds"] == 30 and _in(wf, "brand:length_text")["replace"] == "30"
    assert _in(wf, "brand:sampler")["seed"] == 21
    assert _in(wf, "brand:enhancer")["sampling_mode.seed"] == 21     # the prompt enhancer is seeded too
    assert _in(wf, "brand:enhance")["value"] is True


def test_music_duration_falls_back_to_the_brand():
    assert _in(_build(), "brand:latent")["seconds"] == load_manifest(FIX).audio.music_duration


def test_explicit_bpm_and_key_ride_along_in_the_brief():
    # SA3 has no BPM/key inputs (ACE-Step does); explicit CLI values join the brief, brand defaults don't
    assert _in(_build(bpm=128, keyscale="A minor"), "brand:prompt")["value"] == \
        "a synthwave stream intro, 128 BPM, in A minor"
    assert _in(_build(), "brand:prompt")["value"] == "a synthwave stream intro"


def test_sfx_mode_uses_the_sound_effects_enhancer_and_a_short_default():
    wf = _build(mode="sfx")
    assert _in(wf, "brand:mode")["choice"] == "SFX"
    assert _in(wf, "brand:latent")["seconds"] == audio.SFX_DURATION
    assert _in(wf, "brand:save")["filename_prefix"] == "audio/brand_sfx"


def test_acestep_stays_available_for_music():
    wf = _build(model="acestep")
    assert _in(wf, "brand:unet")["unet_name"] == audio.ACESTEP_MODEL
    assert audio.resolved_model(load_manifest(FIX), "music", "acestep") == audio.ACESTEP_MODEL


def test_sfx_needs_stable_audio():
    with pytest.raises(ValueError, match="Stable Audio"):
        _build(mode="sfx", model="acestep")


def test_a_brand_can_pin_acestep(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("name: B\naudio: { music_model: acestep }\n")
    assert audio.resolved_model(load_manifest(p), "music") == audio.ACESTEP_MODEL


def test_the_sidecar_records_the_brief_and_a_reseed_is_not_drift():
    wf = _build(duration=30)
    assert graph_prompts(wf, "audio", "music") == ("a synthwave stream intro", "")
    other = _build(duration=30)
    _in(other, "brand:sampler")["seed"] = _in(other, "brand:enhancer")["sampling_mode.seed"] = 99
    assert graph_values(wf, "audio", "music") == graph_values(other, "audio", "music")
    sfx = _build(mode="sfx")
    assert graph_prompts(sfx, "audio", "sfx")[0] == "a synthwave stream intro"


def test_the_sfx_prompt_is_the_subject_alone():
    m = load_manifest(FIX)   # has brand music_tags; a sound effect must not inherit them
    assert build_audio_prompt(m, "a sword unsheathing", "sfx") == ("a sword unsheathing", "")


def test_an_unknown_audio_mode_is_rejected():
    with pytest.raises(ValueError, match="music, sfx or foley"):
        _build(mode="karaoke")



def test_sa3_and_foley_reject_what_they_cannot_render():
    import pytest as _pytest
    from scripts.brandkit import audio as A
    from scripts.brandkit.manifest import default_manifest
    m = default_manifest()
    with _pytest.raises(ValueError, match="at least 1"):
        A.check_options(m, "sfx", duration=0.4)       # EmptyLatentAudio's minimum is 1 s
    with _pytest.raises(ValueError, match="makes music"):
        A.check_options(m, "foley", model="acestep")
    A.check_options(m, "sfx", duration=1.0)
    A.check_options(m, "music", model="acestep", duration=0.5)    # ACE-Step is not SA3
    A.check_options(m, "foley", model="hunyuanvideo_foley_fp8_e4m3fn.safetensors")
