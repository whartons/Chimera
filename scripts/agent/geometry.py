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
are fine).

Fragmentation counts SIGNIFICANT parts (`major_parts`: islands with at least 1% of the mesh's
vertices) when mesh_eval reports them. TRELLIS.2 / Pixal3D model eyes, an antenna tip or claws as
separate tiny shells: a clean toy robot had 12 islands but only 3 significant ones (2026-10). Older
checks files without `major_parts` fall back to the raw `loose_parts` count."""
from __future__ import annotations

RENDER_CHECKS_SUFFIX = ".checks.json"

# A coherent solid may legitimately come out as a handful of parts (body + antenna + wheels that
# didn't weld); only MANY islands signal a generation that fragmented. Tunable.
DEFAULT_MAX_LOOSE_PARTS = 8


_ONE_SOLID = " FIX: add one connected solid; avoid disconnected floating pieces"   # reaches the CAD codegen too
# A mesh whose largest island holds less than this share, with more than max_loose_parts islands, has
# shattered: 150 equal shards each fall under the 1% `major_parts` bar, so that count alone read 0 and passed.
MIN_MAIN_SHARE = 0.5


def structural_issues(checks: dict, *, max_loose_parts: int = DEFAULT_MAX_LOOSE_PARTS,
                      strict: bool = False) -> list[str]:
    """Gross, VLM-invisible geometry defects as NOT-MET lines (each with a FIX directive, so the expander
    and the CAD codegen act on them). Missing/None keys are treated as good.

    Does NOT fail on non-manifold or open/boundary edges — those are baseline for surface-net
    image-to-3D output (see module docstring), so failing on them rejects every real mesh. Fails on an
    empty/degenerate mesh, more than `max_loose_parts` significant parts, or a shattered mesh (many islands,
    none dominant). `strict` (CAD) requires ONE solid by raw island count: a scripted part has no tiny
    shells to forgive, and with fine tessellation a hub's vertex count hid 16 floating blades under the 1%
    bar (2026-10)."""
    issues: list[str] = []
    lp = int(checks.get("loose_parts", 1) or 1)
    major = checks.get("major_parts")
    share = checks.get("main_part_share")
    if strict:
        if lp > 1:
            issues.append(f"NOT-MET: the part came out as {lp} separate solids instead of one fused solid."
                          + _ONE_SOLID)
    elif major is not None and int(major) > max_loose_parts:
        issues.append(f"NOT-MET: mesh fragmented into {int(major)} significant parts (each at least 1% "
                      f"of the mesh; more than {max_loose_parts}, so the form did not generate as one "
                      "coherent solid)." + _ONE_SOLID)
    elif major is not None and share is not None and lp > max_loose_parts and float(share) < MIN_MAIN_SHARE:
        issues.append(f"NOT-MET: mesh shattered into {lp} pieces and the largest holds only "
                      f"{float(share):.0%} of it (the form did not generate as one coherent solid)." + _ONE_SOLID)
    elif major is None and lp > max_loose_parts:
        issues.append(f"NOT-MET: mesh fragmented into {lp} disconnected parts "
                      f"(more than {max_loose_parts}; the form did not generate as one coherent solid)."
                      + _ONE_SOLID)
    # An explicit 0 means an empty mesh (flag it); a missing key or None means "not measured"
    # (treat as good, consistent with the other checks) — so guard on `is not None`.
    tc = checks.get("tri_count")
    if tc is not None and int(tc) == 0:
        issues.append("NOT-MET: mesh is empty/degenerate (0 triangles)")
    if checks.get("bounds_ok", True) is False:
        issues.append("NOT-MET: mesh is degenerate (zero/near-zero extent)")
    return issues
