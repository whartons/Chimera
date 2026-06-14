"""Pure mapping from a mesh_eval geometry-checks dict to judge NOT-MET issue lines.

bmesh computes the facts in workflows/templates/blender/mesh_eval.py; this turns the
failed ones into the same 'NOT-MET: ...' lines a VLM judge emits, so they flow through
the unchanged parse_verdict/expander feedback channel. Stdlib only — no bpy, no ComfyUI."""
from __future__ import annotations

RENDER_CHECKS_SUFFIX = ".checks.json"


def structural_issues(checks: dict) -> list[str]:
    """Geometry facts a VLM can't see, as NOT-MET lines. Missing keys are treated as good."""
    issues: list[str] = []
    nm = int(checks.get("non_manifold_edges", 0) or 0)
    if nm > 0:
        issues.append(f"NOT-MET: mesh is not manifold ({nm} non-manifold edges)")
    oe = int(checks.get("open_edges", 0) or 0)
    if oe > 0:
        issues.append(f"NOT-MET: mesh is not watertight ({oe} open edges)")
    lp = int(checks.get("loose_parts", 1) or 1)
    if lp > 1:
        issues.append(f"NOT-MET: mesh has {lp} disconnected parts (expected 1)")
    if int(checks.get("tri_count", 1) or 0) == 0:
        issues.append("NOT-MET: mesh is empty/degenerate (0 triangles)")
    if checks.get("bounds_ok", True) is False:
        issues.append("NOT-MET: mesh is degenerate (zero/near-zero extent)")
    return issues
