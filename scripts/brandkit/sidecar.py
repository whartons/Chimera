"""Build the reproducibility-sidecar metadata for a render (pure, no I/O).

The sidecar must reflect what was ACTUALLY rendered, not the pre-filler intent: fillers
transform prompts inside the built graph (e.g. the video filler appends anti-warp terms to
the negative), so we read the final text back off the graph by stable node title. We also
record the modality-relevant CLI inputs so a future `replay` can reproduce the render.
SCHEMA_VERSION lets replay detect (and refuse/upgrade) older sidecars."""
from __future__ import annotations
import hashlib, json
from .nodes import find_node_by_title, NodeNotFound

SCHEMA_VERSION = 2

# Where the final prompt/negative text lives in each built graph: (pos_title, pos_input),
# (neg_title, neg_input). None means "no such text node" -> "".
_PROMPT_NODES = {
    ("image", None): (("brand:positive", "text"), ("brand:negative", "text")),
    ("video", None): (("brand:positive", "text"), ("brand:negative", "text")),
    ("audio", "music"): (("brand:tags", "tags"), None),
    ("audio", "foley"): (("brand:foley", "prompt"), ("brand:foley", "negative_prompt")),
    ("3d", None): (None, None),
}

# CLI inputs meaningful to each modality/mode (everything else, and any None value, is dropped).
_INPUT_KEYS = {
    ("image", None): ("subject", "asset", "variant", "model", "upscale", "upscale_model"),
    ("video", None): ("subject", "from_image", "length", "fps", "width", "height", "audio",
                      "upscale", "upscale_model"),
    ("audio", "music"): ("subject", "duration", "bpm", "keyscale"),
    ("audio", "foley"): ("subject", "from_video", "duration", "fps"),
    ("3d", None): ("from_image", "octree", "model", "format"),
}


def _key(modality, mode, table):
    """Modality/mode lookup: audio dispatches on mode, others ignore it."""
    if modality == "audio":
        return table[(modality, mode)]
    return table[(modality, None)]


def _read(wf, spec):
    """Read one node-input by (title, input) spec; '' if the node/input is missing."""
    if spec is None:
        return ""
    title, field = spec
    try:
        return find_node_by_title(wf, title)[1].get("inputs", {}).get(field, "") or ""
    except NodeNotFound:
        return ""


def graph_signature(wf):
    """A short, stable hash of the built graph's STRUCTURE — each node's id, class_type, title, and
    its connection edges (list-valued [node_id, output_index] inputs) — EXCLUDING scalar input values
    (seed, prompt, steps, sizes). Two renders from the same template version share a signature; a
    structural template edit changes it. Provenance only — not read by replay. '' for an empty graph."""
    parts = []
    for nid, node in sorted(wf.items()):
        if not isinstance(node, dict):
            continue
        title = node.get("_meta", {}).get("title", "")
        edges = sorted([k, v[0], v[1]] for k, v in node.get("inputs", {}).items()
                       if isinstance(v, list) and len(v) == 2
                       and isinstance(v[0], str) and isinstance(v[1], int))
        parts.append([nid, node.get("class_type", ""), title, edges])
    if not parts:
        return ""
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def graph_prompts(wf, modality, mode):
    """(positive, negative) read back from the built graph, so the sidecar records the text
    the filler actually rendered (including any appended negatives). Missing nodes/inputs -> ''."""
    pos_spec, neg_spec = _key(modality, mode, _PROMPT_NODES)
    return _read(wf, pos_spec), _read(wf, neg_spec)


def relevant_inputs(modality, mode, inputs):
    """The subset of a flat `inputs` dict meaningful to this modality/mode, dropping keys whose
    value is None. Falsy-but-meaningful values (audio=False, length=0) are kept."""
    keys = _key(modality, mode, _INPUT_KEYS)
    return {k: inputs[k] for k in keys if inputs.get(k) is not None}


def build_meta(*, modality, mode, brand, seed, model, watermark, comfy_url, wf, inputs,
               timestamp, fmt=None, comfyui_version=None, pipeline_git_sha=None):
    """Assemble the schema-2 sidecar dict. `model` is the already-resolved model filename
    (the caller resolves Z-Image variants etc.); we do not re-resolve. Top-level prompt/negative
    are kept for backward-compat with schema-1 sidecars; `format` is set only when fmt is given.

    A `provenance` block records what produced the render so it traces back exactly: a structural
    `graph_signature` (always), plus the ComfyUI engine version and the pipeline's git commit
    (`-dirty` if the tree had uncommitted changes) when the caller can supply them (both best-effort,
    omitted when None). Replay ignores `provenance`."""
    pos, neg = graph_prompts(wf, modality, mode)
    meta = {
        "schema": SCHEMA_VERSION,
        "modality": modality, "mode": mode, "brand": brand,
        "seed": seed, "model": model, "watermark": watermark,
        "prompt": pos, "negative": neg,
        "inputs": relevant_inputs(modality, mode, inputs),
        "comfy_url": comfy_url, "timestamp": timestamp,
    }
    if fmt is not None:
        meta["format"] = fmt
    prov = {"graph_signature": graph_signature(wf)}
    if comfyui_version:
        prov["comfyui_version"] = comfyui_version
    if pipeline_git_sha:
        prov["pipeline_git_sha"] = pipeline_git_sha
    meta["provenance"] = prov
    return meta
