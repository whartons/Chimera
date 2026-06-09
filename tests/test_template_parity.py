"""Guard: each module's workflow.*.template.json must stay identical to its canonical copy under
workflows/templates/. The runtime only ever loads the canonical copy (workflow.py _load_template,
video/audio/threed fillers); the module copies are README-linked documentation mirrors, so silent
drift would publish a graph that differs from what actually executes. Compare normalized JSON (not
raw bytes) so whitespace/encoding noise can't false-fail while real node/param drift is caught."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

# (module copy, canonical template). Every modules/*/*.json MUST appear here as a module copy
# (test_every_module_template_is_guarded enforces it). The 4 canonical templates without a module
# mirror — agent-vlm-judge, brand-txt2img, brand-logo-overlay, brand-product-mockup — are out of scope.
PAIRS = [
    ("modules/image/workflow.template.json",                     "workflows/templates/flux2-txt2img.json"),
    ("modules/image/workflow.zimage-txt2img.template.json",      "workflows/templates/brand-zimage-txt2img.json"),
    ("modules/image/workflow.zimage-logo-overlay.template.json", "workflows/templates/brand-zimage-logo-overlay.json"),
    ("modules/image/workflow.zimage-product.template.json",      "workflows/templates/brand-zimage-product.json"),
    ("modules/video/workflow.template.json",                     "workflows/templates/brand-video-i2v.json"),
    ("modules/audio/workflow.music.template.json",               "workflows/templates/brand-audio-music.json"),
    ("modules/audio/workflow.foley.template.json",               "workflows/templates/brand-audio-foley.json"),
    ("modules/threed/workflow.template.json",                    "workflows/templates/brand-3d-image.json"),
]


@pytest.mark.parametrize("module_copy, canonical", PAIRS,
                         ids=[f"{Path(m).parts[1]}/{Path(m).name}" for m, _ in PAIRS])
def test_module_template_matches_canonical(module_copy, canonical):
    mc, cn = ROOT / module_copy, ROOT / canonical
    assert mc.exists(), f"missing module copy {module_copy}"
    assert cn.exists(), f"missing canonical template {canonical}"
    a = json.loads(mc.read_text(encoding="utf-8"))
    b = json.loads(cn.read_text(encoding="utf-8"))
    assert a == b, f"{module_copy} has drifted from {canonical}"


def test_every_module_template_is_guarded():
    # any modules/*/*.json not listed in PAIRS would silently escape the drift guard
    found = {str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.glob("modules/*/*.json")}
    guarded = {m for m, _ in PAIRS}
    assert found == guarded, f"unguarded module templates: {found - guarded}"
