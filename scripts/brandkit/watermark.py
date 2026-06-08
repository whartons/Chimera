"""Opt-in in-graph watermark: composite the brand logo onto a decoded frame inside the
ComfyUI workflow (no host image libs). Reuses LoadImage's mask (1-alpha) the same way the
logo-overlay template does. One shared core (`_inject_watermark`) parametrized by the
frame-source node + sink node serves image (`brand:decode`->`brand:save`), video
(`brand:decode`->`brand:create_video`), and foley (`brand:components`->`brand:create_video`)
graphs; the audio edge into CreateVideo is always left untouched."""
from __future__ import annotations
from .nodes import find_node_by_title


def logo_geometry(canvas, *, logo_px, scale, margin, position):
    """Return (x, y, scale_by) for placing a logo on a canvas. logo_px is the logo's
    on-graph pixel size (native * scale); falls back to canvas*scale if unknown."""
    cw, ch = canvas
    lw, lh = logo_px if logo_px else (int(cw * scale), int(ch * scale))
    mx, my = int(cw * margin), int(ch * margin)
    x = mx if "left" in position else (cw - lw - mx)
    y = my if "top" in position else (ch - lh - my)
    if position == "center":
        x, y = (cw - lw) // 2, (ch - lh) // 2
    return max(0, x), max(0, y), scale


def _inject_watermark(wf, *, manifest, logo_name, canvas, logo_px, sink_title,
                      sink_input="images", frames_title="brand:decode"):
    """Composite the brand logo (LoadImage mask, scaled) over the frame-source node, then rewire
    the sink node's image input to the composite. Ids 90-96 are reserved for watermark nodes."""
    if not logo_name:
        raise ValueError("watermark requested but no brand logo to stamp")
    w = manifest.watermark
    frames_id, _ = find_node_by_title(wf, frames_title)
    _, sink = find_node_by_title(wf, sink_title)
    x, y, scale_by = logo_geometry(canvas, logo_px=logo_px, scale=w.scale,
                                   margin=w.margin, position=w.position)
    wf["90"] = {"class_type": "LoadImage", "_meta": {"title": "brand:watermark_load"},
                "inputs": {"image": logo_name}}
    wf["91"] = {"class_type": "ImageScaleBy", "_meta": {"title": "brand:watermark_scale"},
                "inputs": {"image": ["90", 0], "upscale_method": "lanczos", "scale_by": scale_by}}
    wf["92"] = {"class_type": "InvertMask", "inputs": {"mask": ["90", 1]}}
    wf["93"] = {"class_type": "MaskToImage", "inputs": {"mask": ["92", 0]}}
    wf["94"] = {"class_type": "ImageScaleBy",
                "inputs": {"image": ["93", 0], "upscale_method": "lanczos", "scale_by": scale_by}}
    wf["95"] = {"class_type": "ImageToMask", "inputs": {"image": ["94", 0], "channel": "red"}}
    wf["96"] = {"class_type": "ImageCompositeMasked", "_meta": {"title": "brand:watermark_composite"},
                "inputs": {"destination": [frames_id, 0], "source": ["91", 0],
                           "x": x, "y": y, "resize_source": False, "mask": ["95", 0]}}
    sink["inputs"][sink_input] = ["96", 0]
    return wf


def inject_image_watermark(wf, *, manifest, logo_name, canvas, logo_px=None):
    """Image graphs: stamp the logo onto the decoded image before SaveImage."""
    return _inject_watermark(wf, manifest=manifest, logo_name=logo_name, canvas=canvas,
                             logo_px=logo_px, sink_title="brand:save")


def inject_video_watermark(wf, *, manifest, logo_name, canvas, logo_px=None):
    """Video graphs: stamp the logo onto the decoded FRAME BATCH before CreateVideo, leaving
    the synced audio edge to CreateVideo untouched."""
    return _inject_watermark(wf, manifest=manifest, logo_name=logo_name, canvas=canvas,
                             logo_px=logo_px, sink_title="brand:create_video")


def inject_foley_watermark(wf, *, manifest, logo_name, canvas, logo_px=None):
    """Foley muxed-video graphs: stamp the logo onto the source FRAME BATCH (brand:components)
    before CreateVideo. The foley sampler keeps reading the clean frames; the audio edge is
    untouched."""
    return _inject_watermark(wf, manifest=manifest, logo_name=logo_name, canvas=canvas,
                             logo_px=logo_px, sink_title="brand:create_video",
                             frames_title="brand:components")
