from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.audio import build
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_music_fills_tags_seed_duration_bpm_keyscale():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="dark sting, instrumental", negative="", seed=7,   # the ACE-Step graph
               mode="music", duration=6.0, bpm=120, keyscale="A minor", model="acestep")
    enc = find_node_by_title(wf, "brand:tags")[1]["inputs"]
    assert enc["tags"] == "dark sting, instrumental"
    assert enc["seed"] == 7 and enc["duration"] == 6.0 and enc["bpm"] == 120
    assert enc["keyscale"] == "A minor"
    assert find_node_by_title(wf, "brand:sampler")[1]["inputs"]["seed"] == 7
    assert find_node_by_title(wf, "brand:latent")[1]["inputs"]["seconds"] == 6.0

def test_acestep_uses_the_manifest_bpm_and_duration_when_unset():
    # (Stable Audio 3, the default music model, is covered in test_audio_sa3.py)
    m = load_manifest(FIX)  # fixture sets no music_model, music_bpm=90
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="music", model="acestep")
    enc = find_node_by_title(wf, "brand:tags")[1]["inputs"]
    assert enc["bpm"] == 90 and enc["duration"] == 8.0  # manifest bpm, default duration
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == \
        "acestep_v1.5_xl_turbo_bf16.safetensors"

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

def test_resolved_model_matches_graph_music_and_foley():
    # B6: the resolver is the single source of truth — equal to what build() wrote, per mode
    from scripts.brandkit.audio import resolved_model
    m = load_manifest(FIX)
    wfm = build(ROOT, m, positive="x", negative="", seed=1, mode="music")   # Stable Audio 3 (checkpoint)
    assert resolved_model(m, "music") == \
        find_node_by_title(wfm, "brand:ckpt")[1]["inputs"]["ckpt_name"]
    wff = build(ROOT, m, positive="x", negative="", seed=1, mode="foley", from_video="s.mp4",
                frame_rate=24.0, duration=2.0, fps=24.0)
    assert resolved_model(m, "foley") == \
        find_node_by_title(wff, "brand:foley_model")[1]["inputs"]["model_name"]
    # explicit override flows through both paths identically
    wfo = build(ROOT, m, positive="x", negative="", seed=1, mode="foley", from_video="s.mp4",
                frame_rate=24.0, duration=2.0, fps=24.0, model="ov.safetensors")
    assert resolved_model(m, "foley", "ov.safetensors") == "ov.safetensors" == \
        find_node_by_title(wfo, "brand:foley_model")[1]["inputs"]["model_name"]


def test_foley_watermark_injected_over_components_keeps_audio():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="music", seed=1, mode="foley", watermark=True,
               from_video="s.mp4", frame_rate=25.0, duration=3.0, fps=25.0,
               watermark_logo="primary.png", logo_px=(120, 120), width=768, height=512)
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    foley_id, _ = find_node_by_title(wf, "brand:foley")
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert cv["images"] == [cid, 0] and cv["audio"] == [foley_id, 0]



def test_lyrics_reach_ace_step_and_nothing_else():
    # ACE-Step was kept for songs with vocals, but the CLI had no way to send it words
    import pytest
    from scripts.brandkit.audio import check_options
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="anthem", negative="", seed=3, mode="music", model="acestep",
               lyrics="[verse]\nsteel and fire")
    assert find_node_by_title(wf, "brand:tags")[1]["inputs"]["lyrics"] == "[verse]\nsteel and fire"
    plain = build(ROOT, m, positive="anthem", negative="", seed=3, mode="music", model="acestep")
    assert find_node_by_title(plain, "brand:tags")[1]["inputs"]["lyrics"] == ""
    with pytest.raises(ValueError, match="add --model acestep"):
        check_options(m, "music", lyrics="la la")                # Stable Audio 3 doesn't sing
    with pytest.raises(ValueError, match="no vocals"):
        check_options(m, "sfx", lyrics="la la")


def test_a_lyric_render_gets_room_to_sing_and_ace_step_runs_comfys_schedule():
    # ACE-Step sang in 40 s and not at all in 20 s; the brand's stinger length (8 s) would never sing
    from scripts.brandkit.audio import LYRICS_SECONDS, music_seconds
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="anthem", negative="", seed=3, mode="music", model="acestep", lyrics="[Verse 1]\nla")
    assert find_node_by_title(wf, "brand:tags")[1]["inputs"]["duration"] == LYRICS_SECONDS
    assert find_node_by_title(wf, "brand:latent")[1]["inputs"]["seconds"] == LYRICS_SECONDS
    assert music_seconds(m) == m.audio.music_duration                       # no lyrics: the brand's length
    short = build(ROOT, m, positive="anthem", negative="", seed=3, mode="music", model="acestep", lyrics="la",
                  duration=20.0)
    assert find_node_by_title(short, "brand:tags")[1]["inputs"]["duration"] == 20.0   # an explicit length wins
    # the shift every Comfy ACE-Step 1.5 template uses (Chimera's graph had 1.73)
    assert find_node_by_title(wf, "brand:model_sampling")[1]["inputs"]["shift"] == 3.0


def test_music_sidecars_record_the_lyrics_and_replay_sends_them_back():
    from scripts.brandkit.sidecar import relevant_inputs
    from scripts.brandkit.replay import args_from_sidecar
    assert relevant_inputs("audio", "music", {"subject": "s", "lyrics": "la"})["lyrics"] == "la"
    s = {"schema": 2, "modality": "audio", "mode": "music", "brand": None, "seed": 3,
         "model": "acestep_v1.5_xl_turbo_bf16.safetensors", "inputs": {"subject": "anthem", "lyrics": "[verse]\nla"}}
    assert args_from_sidecar(s).lyrics == "[verse]\nla"



# --- ComfyUI's ACE-Step and foley bounds are checked before anything uploads (2026-10-25 review) ------------
# Bounds from ComfyUI 0.41.1's /object_info: TextEncodeAceStepAudio1.5 keyscale (a 34-value combo) and bpm
# 10-300, EmptyAceStep1.5LatentAudio seconds 1-1000, HunyuanFoleySampler duration 1-60 and frame_rate 1-120.
import pytest  # noqa: E402
from scripts.brandkit.audio import check_options  # noqa: E402


def _ace_keyscale(**kw):
    wf = build(ROOT, load_manifest(FIX), positive="x", negative="", seed=1, mode="music", model="acestep", **kw)
    return find_node_by_title(wf, "brand:tags")[1]["inputs"]["keyscale"]


@pytest.mark.parametrize("given, sent", [("F# Minor", "F# minor"), ("f#minor", "F# minor"),
                                         ("  bb   MAJOR ", "Bb major"), ("Db minor", "Db minor")])
def test_ace_step_gets_its_own_spelling_of_the_key(given, sent):
    # the encoder's keyscale is a combo: "F# Minor" was sent as typed and ComfyUI answered HTTP 400
    assert _ace_keyscale(keyscale=given) == sent


def test_an_unknown_key_is_refused_with_the_valid_ones():
    m = load_manifest(FIX)
    with pytest.raises(ValueError, match=r"--keyscale 'H minor'.*C major.*B minor"):
        check_options(m, "music", model="acestep", keyscale="H minor")
    m.audio.music_keyscale = "F# dorian"   # the brand's default is checked too
    with pytest.raises(ValueError, match="music_keyscale 'F# dorian'"):
        check_options(m, "music", model="acestep")


def test_stable_audio_3_keeps_any_key_text():
    # SA3 has no key input: the text only joins the prompt, so anything goes
    m = load_manifest(FIX)
    check_options(m, "music", keyscale="F# dorian")
    wf = build(ROOT, m, positive="anthem", negative="", seed=1, mode="music", keyscale="F# dorian")
    assert "in F# dorian" in find_node_by_title(wf, "brand:prompt")[1]["inputs"]["value"]


def test_ace_step_bpm_must_be_10_to_300():
    m = load_manifest(FIX)
    for bad in (9, 301):
        with pytest.raises(ValueError, match="10 to 300"):
            check_options(m, "music", model="acestep", bpm=bad)
    check_options(m, "music", model="acestep", bpm=10)
    check_options(m, "music", model="acestep", bpm=300)
    m.audio.music_bpm = 400
    with pytest.raises(ValueError, match="music_bpm 400"):
        check_options(m, "music", model="acestep")


def test_ace_step_renders_1_to_1000_seconds():
    m = load_manifest(FIX)
    for bad in (0.5, 1001.0):
        with pytest.raises(ValueError, match="ACE-Step renders 1 to 1000 s"):
            check_options(m, "music", model="acestep", duration=bad)
    check_options(m, "music", model="acestep", duration=1.0)


def test_stable_audio_3_renders_at_most_1000_seconds_and_checks_the_brand_length_too():
    m = load_manifest(FIX)
    with pytest.raises(ValueError, match="at most 1000 s"):
        check_options(m, "sfx", duration=1001.0)
    m.audio.music_duration = 0.5   # a brand.yaml default, not a flag: ComfyUI refused it all the same
    with pytest.raises(ValueError, match="brand audio.music_duration 0.5"):
        check_options(m, "music")


def test_foley_renders_1_to_60_seconds_at_up_to_120_fps():
    m = load_manifest(FIX)
    for bad in (0.5, 75.0):
        with pytest.raises(ValueError, match="1 to 60 s"):
            check_options(m, "foley", duration=bad)
    with pytest.raises(ValueError, match="1 to 120 fps"):
        check_options(m, "foley", duration=5.0, frame_rate=240.0)
    check_options(m, "foley", duration=60.0, frame_rate=120.0)
