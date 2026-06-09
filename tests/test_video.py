from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.video import build
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_video_fills_prompt_size_seed_model_audio():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="a rover driving", negative="bad", seed=11, watermark=False,
               from_image="rover.png", length=49, fps=24, audio=True, width=960, height=544)
    assert find_node_by_title(wf, "brand:positive")[1]["inputs"]["text"] == "a rover driving"
    # brand negative + the video-critical anti-frozen/anti-silence terms
    neg_text = find_node_by_title(wf, "brand:negative")[1]["inputs"]["text"]
    assert "bad" in neg_text and "frozen" in neg_text and "silence" in neg_text
    assert find_node_by_title(wf, "brand:noise")[1]["inputs"]["noise_seed"] == 11
    vl = find_node_by_title(wf, "brand:video_latent")[1]["inputs"]
    assert vl["width"] == 960 and vl["height"] == 544 and vl["length"] == 49
    assert find_node_by_title(wf, "brand:resize")[1]["inputs"]["width"] == 960
    assert find_node_by_title(wf, "brand:cond")[1]["inputs"]["frame_rate"] == 24
    al = find_node_by_title(wf, "brand:audio_latent")[1]["inputs"]
    assert al["frames_number"] == 49 and al["frame_rate"] == 24
    assert find_node_by_title(wf, "brand:load_image")[1]["inputs"]["image"] == "rover.png"
    assert find_node_by_title(wf, "brand:create_video")[1]["inputs"]["fps"] == 24
    ck = find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"]
    assert find_node_by_title(wf, "brand:encoder")[1]["inputs"]["ckpt_name"] == ck
    assert find_node_by_title(wf, "brand:audio_vae")[1]["inputs"]["ckpt_name"] == ck

def test_video_audio_off_drops_create_video_audio_edge():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=False, width=768, height=512)
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert "audio" not in cv

def test_video_model_override_from_arg():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512,
               model="ltx-2.3-22b-distilled-1.1.safetensors")
    assert find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"] == "ltx-2.3-22b-distilled-1.1.safetensors"

def test_video_watermark_injected_over_frames():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=True,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512,
               watermark_logo="primary.png", logo_px=(120, 120))
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert cv["images"] == [cid, 0]
    assert cv["audio"] == ["24", 0]

def test_video_upscale_off_by_default_no_nodes():
    import pytest
    from scripts.brandkit.nodes import NodeNotFound
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512)
    with pytest.raises(NodeNotFound):
        find_node_by_title(wf, "brand:video_upscale")
    # decode still reads the separated video latent directly
    assert find_node_by_title(wf, "brand:decode")[1]["inputs"]["samples"] == ["22", 0]

def test_video_upscale_splices_latent_before_decode():
    from scripts.brandkit.video import DEFAULT_VIDEO_UPSCALE_MODEL
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512,
               upscale=True)
    assert find_node_by_title(wf, "brand:video_upscale_model")[1]["inputs"]["model_name"] == \
        DEFAULT_VIDEO_UPSCALE_MODEL
    up = find_node_by_title(wf, "brand:video_upscale")[1]["inputs"]
    # the upsampler takes over the original separate->decode video-latent edge and the video VAE
    assert up["samples"] == ["22", 0]
    assert up["upscale_model"] == ["70", 0]
    assert up["vae"] == ["1", 2]
    # decode now reads the upscaled latent
    assert find_node_by_title(wf, "brand:decode")[1]["inputs"]["samples"] == ["71", 0]

def test_video_upscale_model_override():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512,
               upscale=True, upscale_model="ltx-2-spatial-upscaler-x2-1.0.safetensors")
    assert find_node_by_title(wf, "brand:video_upscale_model")[1]["inputs"]["model_name"] == \
        "ltx-2-spatial-upscaler-x2-1.0.safetensors"

def test_video_upscale_and_watermark_coexist():
    # both on: latent upscale precedes decode, watermark composites over the (2x) decoded frames
    from scripts.brandkit.watermark import logo_geometry
    m = load_manifest(FIX)
    logo_px = (120, 120)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=True,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512,
               watermark_logo="primary.png", logo_px=logo_px, upscale=True)
    # upscale node present and decode rewired to it (order didn't break)
    find_node_by_title(wf, "brand:video_upscale")
    decode_id, decode = find_node_by_title(wf, "brand:decode")
    assert decode["inputs"]["samples"] == ["71", 0]
    # watermark composites over the decoded frames, then feeds create_video
    comp_id, comp = find_node_by_title(wf, "brand:watermark_composite")
    assert comp["inputs"]["destination"] == [decode_id, 0]
    assert find_node_by_title(wf, "brand:create_video")[1]["inputs"]["images"] == [comp_id, 0]
    # the watermark geometry must be computed against the DOUBLED canvas (1536x1024), not the
    # base (768x512) — pins that the 2x upscale flowed through into the placement math.
    ex_x, ex_y, _ = logo_geometry((1536, 1024), logo_px=logo_px, scale=m.watermark.scale,
                                  margin=m.watermark.margin, position=m.watermark.position)
    assert (comp["inputs"]["x"], comp["inputs"]["y"]) == (ex_x, ex_y)
    # sanity: the doubled-canvas placement differs from what the base canvas would give
    base_x, base_y, _ = logo_geometry((768, 512), logo_px=logo_px, scale=m.watermark.scale,
                                      margin=m.watermark.margin, position=m.watermark.position)
    assert (comp["inputs"]["x"], comp["inputs"]["y"]) != (base_x, base_y)


def test_resolved_model_matches_graph_ckpt():
    # B6: the filler's resolver is the single source of truth — it must equal what build() wrote
    from scripts.brandkit.video import resolved_model
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False,
               from_image="r.png", length=97, fps=25, audio=True, width=768, height=512)
    assert resolved_model(m) == find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"]


def test_resolved_upscale_model_matches_graph():
    from scripts.brandkit.video import resolved_upscale_model
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="x", negative="", seed=1, watermark=False, from_image="r.png",
               length=97, fps=25, audio=True, width=768, height=512, upscale=True)
    assert resolved_upscale_model(m) == \
        find_node_by_title(wf, "brand:video_upscale_model")[1]["inputs"]["model_name"]


def test_resolved_upscale_model_brand_override_flows_to_graph_and_resolver(tmp_path):
    # the brand-level video.upscale_model must reach BOTH the graph node and the sidecar resolver,
    # and an explicit CLI override must win over it in both — pins the precedence single-source.
    from scripts.brandkit.manifest import load_manifest as _load
    from scripts.brandkit.video import resolved_upscale_model
    p = tmp_path / "brand.yaml"
    p.write_text('name: "VU"\nvideo: { upscale_model: "brand-up.safetensors" }\n', encoding="utf-8")
    mv = _load(p)
    wf = build(ROOT, mv, positive="x", negative="", seed=1, watermark=False, from_image="r.png",
               length=97, fps=25, audio=True, width=768, height=512, upscale=True)
    node = find_node_by_title(wf, "brand:video_upscale_model")[1]["inputs"]["model_name"]
    assert resolved_upscale_model(mv) == "brand-up.safetensors" == node
    wf2 = build(ROOT, mv, positive="x", negative="", seed=1, watermark=False, from_image="r.png",
                length=97, fps=25, audio=True, width=768, height=512, upscale=True,
                upscale_model="cli-up.safetensors")
    node2 = find_node_by_title(wf2, "brand:video_upscale_model")[1]["inputs"]["model_name"]
    assert resolved_upscale_model(mv, "cli-up.safetensors") == "cli-up.safetensors" == node2


def test_video_upscale_model_default_none_and_loaded():
    # The Video dataclass exposes a per-modality upscale override that defaults to None, and
    # load_manifest reads brand.yaml video.upscale_model into it (parallel to defaults.upscale_model
    # for image). This is what generate.py resolves as the video --upscale fallback.
    from scripts.brandkit.manifest import Video, load_manifest as _load
    import tempfile
    assert Video().upscale_model is None
    m = load_manifest(FIX)               # fixture has no video block -> stays None
    assert m.video.upscale_model is None
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "brand.yaml"
        p.write_text(
            'name: "VU"\n'
            'video: { upscale_model: "ltx-2-spatial-upscaler-x2-1.0.safetensors" }\n',
            encoding="utf-8")
        mv = _load(p)
    assert mv.video.upscale_model == "ltx-2-spatial-upscaler-x2-1.0.safetensors"
