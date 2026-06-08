import json
from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.watermark import logo_geometry, inject_image_watermark
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_logo_geometry_bottom_right():
    # canvas 1000x800, logo px 100x100, margin 0.05 -> bottom-right corner
    x, y, scale_by = logo_geometry((1000, 800), logo_px=(100, 100), scale=0.2, margin=0.05,
                                   position="bottom-right")
    assert x == 1000 - 100 - 50 and y == 800 - 100 - 40 and scale_by == 0.2

def test_inject_adds_composite_and_rewires_save():
    wf = json.loads((ROOT / "workflows/templates/brand-txt2img.json").read_text())
    m = load_manifest(FIX)
    inject_image_watermark(wf, manifest=m, logo_name="primary.png", canvas=(1024, 1024),
                           logo_px=(160, 160))
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    decode_id, _ = find_node_by_title(wf, "brand:decode")
    _, save = find_node_by_title(wf, "brand:save")
    assert save["inputs"]["images"] == [cid, 0]
    assert wf[cid]["inputs"]["destination"] == [decode_id, 0]

def test_inject_video_watermark_rewires_create_video_and_keeps_audio():
    wf = json.loads((ROOT / "workflows/templates/brand-video-i2v.json").read_text())
    m = load_manifest(FIX)
    from scripts.brandkit.watermark import inject_video_watermark
    inject_video_watermark(wf, manifest=m, logo_name="primary.png", canvas=(768, 512),
                           logo_px=(120, 120))
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    decode_id, _ = find_node_by_title(wf, "brand:decode")
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert cv["images"] == [cid, 0]
    assert wf[cid]["inputs"]["destination"] == [decode_id, 0]
    assert cv["audio"] == ["24", 0]   # audio edge preserved

def test_inject_foley_watermark_composites_components_keeps_audio():
    wf = json.loads((ROOT / "workflows/templates/brand-audio-foley.json").read_text())
    m = load_manifest(FIX)
    from scripts.brandkit.watermark import inject_foley_watermark
    foley_id, _ = find_node_by_title(wf, "brand:foley")
    comp_src, _ = find_node_by_title(wf, "brand:components")
    inject_foley_watermark(wf, manifest=m, logo_name="primary.png", canvas=(768, 512),
                           logo_px=(120, 120))
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    cv = find_node_by_title(wf, "brand:create_video")[1]["inputs"]
    assert cv["images"] == [cid, 0]                 # muxed frames are watermarked
    assert wf[cid]["inputs"]["destination"] == [comp_src, 0]  # composite over clean components
    assert cv["audio"] == [foley_id, 0]             # audio edge preserved
    # the foley sampler still reads the CLEAN frames, not the watermark composite
    assert find_node_by_title(wf, "brand:foley")[1]["inputs"]["image"] == [comp_src, 0]
