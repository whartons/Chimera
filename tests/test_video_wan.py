"""Video: Wan 2.2 is the default (fast 4-step image-to-video; `quality="full"` for 20 steps; `camera=` for
Fun Camera moves); LTX-2.3 stays for clips with built-in synced audio (model="ltx23")."""
from pathlib import Path
import pytest
from scripts.brandkit import video
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.nodes import find_node_by_title, NodeNotFound

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"


def _in(wf, title):
    return find_node_by_title(wf, title)[1]["inputs"]


def _build(**kw):
    return video.build(ROOT, load_manifest(FIX), positive="rain on a parked car", negative="blurry", seed=9,
                       from_image="car.png", **kw)


def test_wan22_is_the_default_fast_4_step_at_its_native_16_fps():
    assert video.resolved_model(load_manifest(FIX)) == video.WAN22_I2V
    wf = _build()
    assert _in(wf, "brand:unet_high")["unet_name"] == "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
    assert _in(wf, "brand:unet_low")["unet_name"] == "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
    assert _in(wf, "brand:load_image")["image"] == "car.png"
    assert _in(wf, "brand:positive")["text"] == "rain on a parked car"
    assert _in(wf, "brand:negative")["text"].startswith("blurry, ")     # brand negative + Wan's own
    i2v = _in(wf, "brand:i2v")
    assert (i2v["width"], i2v["height"], i2v["length"]) == (768, 512, 81)   # brand size, Wan's 81 frames
    assert _in(wf, "brand:create_video")["fps"] == 16
    hi, lo = _in(wf, "brand:sampler_high"), _in(wf, "brand:sampler_low")
    assert (hi["steps"], hi["cfg"], hi["end_at_step"], hi["noise_seed"]) == (4, 1.0, 2, 9)
    assert (lo["steps"], lo["start_at_step"]) == (4, 2)
    lora_id, _ = find_node_by_title(wf, "brand:lora_high")
    assert _in(wf, "brand:model_sampling_high")["model"] == [lora_id, 0]


def test_full_quality_drops_the_4_step_loras_and_samples_20_steps():
    wf = _build(quality="full")
    with pytest.raises(NodeNotFound):
        find_node_by_title(wf, "brand:lora_high")
    unet_id, _ = find_node_by_title(wf, "brand:unet_high")
    assert _in(wf, "brand:model_sampling_high")["model"] == [unet_id, 0]
    hi, lo = _in(wf, "brand:sampler_high"), _in(wf, "brand:sampler_low")
    assert (hi["steps"], hi["cfg"], hi["end_at_step"]) == (20, 3.5, 10)
    assert (lo["start_at_step"], lo["cfg"]) == (10, 3.5)


def test_camera_moves_use_fun_camera_at_full_quality_by_default():
    # 4-step Fun Camera kept the camera locked but cut scene motion to ~1/3 (2026-10 measurement)
    wf = _build(camera="pan-left")
    assert _in(wf, "brand:unet_high")["unet_name"] == "wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors"
    cam = _in(wf, "brand:camera")
    assert cam["camera_pose"] == "Pan Left" and (cam["width"], cam["height"], cam["length"]) == (768, 512, 81)
    assert _in(wf, "brand:sampler_high")["steps"] == 20
    assert _in(_build(camera="static", quality="fast"), "brand:sampler_high")["steps"] == 4


def test_every_camera_name_maps_to_a_fun_camera_pose():
    assert {"static", "pan-left", "pan-right", "pan-up", "pan-down", "zoom-in", "zoom-out"} <= set(video.CAMERA_POSES)
    for name, pose in video.CAMERA_POSES.items():
        assert _in(_build(camera=name), "brand:camera")["camera_pose"] == pose


def test_ltx23_stays_available_for_built_in_audio(tmp_path):
    assert _in(_build(model="ltx23"), "brand:ckpt")["ckpt_name"] == video.LTX23_MODEL
    p = tmp_path / "b.yaml"
    p.write_text("name: B\nvideo: { model: ltx23 }\n")              # a brand may pin LTX by short name
    assert video.resolved_model(load_manifest(p)) == video.LTX23_MODEL


def test_resolved_settings_differ_by_family():
    m = load_manifest(FIX)
    wan = video.resolved_settings(m)
    assert (wan["length"], wan["fps"], wan["audio"], wan["quality"]) == (81, 16, False, "fast")
    ltx = video.resolved_settings(m, model="ltx23")
    assert (ltx["length"], ltx["fps"], ltx["audio"], ltx["quality"]) == (97, 25, True, None)   # brand video: block
    cam = video.resolved_settings(m, camera="static")
    assert cam["quality"] == "full" and cam["camera"] == "static"
    assert video.resolved_settings(m, length=121, fps=24)["length"] == 121                       # explicit flags win


def test_wan_sizes_snap_down_to_multiples_of_16():
    i2v = _in(_build(width=770, height=500), "brand:i2v")
    assert (i2v["width"], i2v["height"]) == (768, 496)


def test_wan_has_no_latent_upscaler():
    with pytest.raises(ValueError, match="ltx23"):
        _build(upscale=True)


def test_a_camera_move_needs_wan():
    with pytest.raises(ValueError, match="Fun Camera"):
        _build(model="ltx23", camera="static")


def test_the_watermark_stamps_wan_frames_before_create_video():
    wf = _build(watermark=True, watermark_logo="primary.png", logo_px=(100, 100))
    comp_id, _ = find_node_by_title(wf, "brand:watermark_composite")
    assert _in(wf, "brand:create_video")["images"] == [comp_id, 0]


def test_bad_inputs_are_rejected_with_the_valid_choices():
    with pytest.raises(ValueError, match="from_image"):
        video.build(ROOT, load_manifest(FIX), positive="x", negative="", seed=1)
    with pytest.raises(ValueError, match="static"):
        _build(camera="dolly")
    with pytest.raises(ValueError, match="fast"):
        _build(quality="ultra")



def test_lengths_snap_to_the_frame_count_the_family_renders():
    # ComfyUI renders 4k+1 (Wan) / 8k+1 (LTX) frames and floors anything else; Wan's Fun Camera crashed on it
    from scripts.brandkit.manifest import default_manifest
    from scripts.brandkit.video import resolved_settings
    m = default_manifest()
    assert [resolved_settings(m, length=n)["length"] for n in (81, 96, 100, 120)] == [81, 93, 97, 117]
    assert [resolved_settings(m, model="ltx23", length=n)["length"] for n in (97, 100, 121)] == [97, 97, 121]
    assert resolved_settings(m, camera="static", length=96)["length"] == 93


def test_family_checks_read_the_file_name_of_a_model_in_a_subfolder():
    from scripts.brandkit.video import is_wan
    from scripts.brandkit.workflow import family
    from scripts.brandkit.threed import family as family3d
    assert is_wan("video\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors")
    assert family("qwen\\qwen_image_2.1_int8_convrot.safetensors") == "qwen"
    assert family("diffusion/z_image_turbo_nvfp4.safetensors") == "zimage"
    assert family3d("3d/trellis_2_int8_convrot.safetensors") == "trellis2"
