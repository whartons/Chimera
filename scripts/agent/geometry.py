"""Pure mapping from a mesh_eval geometry-checks dict to judge NOT-MET issue lines.

bmesh computes the facts in workflows/templates/blender/mesh_eval.py; this turns the
failed ones into the same 'NOT-MET: ...' lines a VLM judge emits, so they flow through
the unchanged parse_verdict/expander feedback channel. Stdlib only — no bpy, no ComfyUI.

Calibrated for image-to-3D (Hunyuan3D) output. Live runs showed raw Hunyuan3D meshes are
INHERENTLY heavily non-manifold (~34% of edges are >2-face junctions, even with no welding)
and carry some boundary edges — that is normal for surface-net extraction, not a defect. So
non_manifold_edges and open_edges are NO LONGER hard fails (gating on them rejected every real
mesh and thrashed the loop); they stay in the checks.json sidecar for provenance. What remains
is genuinely diagnostic AND hard for a VLM to read off a render: an empty/degenerate mesh, or a
generation that fragmented into many disconnected islands (a few parts — body + antenna, etc. —
are fine)."""
from __future__ import annotations

RENDER_CHECKS_SUFFIX = ".checks.json"

# A coherent solid may legitimately come out as a handful of parts (body + antenna + wheels that
# didn't weld); only MANY islands signal a generation that fragmented. Tunable.
DEFAULT_MAX_LOOSE_PARTS = 8


def structural_issues(checks: dict, *, max_loose_parts: int = DEFAULT_MAX_LOOSE_PARTS) -> list[str]:
    """Gross, VLM-invisible geometry defects as NOT-MET lines. Missing/None keys are treated as good.

    Does NOT fail on non-manifold or open/boundary edges — those are baseline for surface-net
    image-to-3D output (see module docstring), so failing on them rejects every real mesh. Fails only
    on an empty/degenerate mesh or a fragmentation into more than `max_loose_parts` islands."""
    issues: list[str] = []
    lp = int(checks.get("loose_parts", 1) or 1)
    if lp > max_loose_parts:
        issues.append(f"NOT-MET: mesh fragmented into {lp} disconnected parts "
                      f"(more than {max_loose_parts}; the form did not generate as one coherent solid)")
    # An explicit 0 means an empty mesh (flag it); a missing key or None means "not measured"
    # (treat as good, consistent with the other checks) — so guard on `is not None`.
    tc = checks.get("tri_count")
    if tc is not None and int(tc) == 0:
        issues.append("NOT-MET: mesh is empty/degenerate (0 triangles)")
    if checks.get("bounds_ok", True) is False:
        issues.append("NOT-MET: mesh is degenerate (zero/near-zero extent)")
    return issues
