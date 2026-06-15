"""Phase 4b finalize primitives shared by the CLI (generate.py finalize-texture) and the loop tail
(scripts/agent/finalize.py): the mesh_finalize Blender param dict and the auto-repaint view generator.
Both are pure / inject their I/O so they're unit-testable without ComfyUI or Blender."""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path

from scripts.brandkit import repaint as repaint_filler

FINALIZE_TEMPLATE = "mesh_finalize.py"   # Blender bake template under workflows/templates/blender/
FINALIZE_TIMEOUT = 1800                  # bake + N-view albedo projection (seconds)


class FinalizeError(RuntimeError):
    """Raised when view generation under-produces, or the bake yields no textured GLB."""


def finalize_params(*, mesh, view_paths, azimuths, brand, seed, elevation, back_fill, palette,
                    texture_res, samples, res, out_dir) -> dict:
    """Single source of truth for the mesh_finalize.py Blender job params (CLI + loop both build this)."""
    return {"mesh": str(mesh), "out_dir": str(out_dir), "stem": f"{brand or 'finalize'}_{seed}",
            "view_images": [str(v) for v in view_paths], "azimuths": list(azimuths),
            "elevation": elevation, "back_fill": back_fill, "palette": list(palette),
            "texture_res": texture_res, "samples": samples, "res": list(res), "seed": seed}


def repaint_views(client, *, mesh, concept, subject, azimuths, comfy_output_dir, repo_root,
                  blender_runner, seed, res=1024, elevation=15.0, cn_strength=0.7, ip_weight=0.8,
                  blender_bin=None):
    """Render per-view depth (Blender) + SDXL depth-ControlNet + IPAdapter repaint (ComfyUI) for each
    azimuth, via repaint.generate_views. Returns (view_paths, azimuths). Depth maps go to a temp dir
    (cleaned); repainted views land in comfy_output_dir. Raises FinalizeError on under-production."""
    render_views_template = Path(repo_root) / "workflows" / "templates" / "blender" / "render_views.py"
    rv_tmp = Path(tempfile.mkdtemp(prefix="chimera_rv_"))
    try:
        view_paths, _ = repaint_filler.generate_views(
            client, mesh=mesh, concept_path=concept, subject=subject, azimuths=list(azimuths),
            comfy_output_dir=comfy_output_dir, out_dir=rv_tmp, elevation=elevation,
            render_views_template=render_views_template, blender_runner=blender_runner,
            seed=seed, res=res, cn_strength=cn_strength, ip_weight=ip_weight, blender_bin=blender_bin)
    finally:
        shutil.rmtree(rv_tmp, ignore_errors=True)
    if len(view_paths) != len(azimuths):
        raise FinalizeError(f"expected {len(azimuths)} views but got {len(view_paths)} "
                            "(render_views/repaint under-produced)")
    return [Path(v) for v in view_paths], list(azimuths)
