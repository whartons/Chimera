"""Phase 4b in-loop finalize: after the mesh3d loop picks a winner, texture it via the multi-view
auto-repaint bake, re-judge the textured result (informational, non-gating), and emit a textured GLB
+ sidecar. Brand-optional. Non-fatal: any failure leaves the (untextured) winner intact. Shares
brandkit.finalize primitives with the generate.py finalize-texture CLI; orchestration mirrors
render_generate.py (its own Blender call + route + montage + sidecar)."""
from __future__ import annotations
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

from scripts.brandkit import blender as _blender
from scripts.brandkit import finalize as finalize_core
from scripts.brandkit import montage
from scripts.brandkit.outputs import route_output, write_sidecar
from scripts.brandkit.sidecar import build_render_meta
from scripts.agent.rubric import build_rubric
from scripts.agent.render_generate import RENDER_TEXTURE_SUFFIX
from scripts.generate import git_provenance

# In-loop finalize knobs — the proven finalize-texture defaults. Fine-tuning / true retries happen
# via the standalone `generate.py finalize-texture` CLI (the printed retry command).
_ELEVATION = 15.0
_CN_STRENGTH = 0.7
_IP_WEIGHT = 0.8
_SAMPLES = 48
_RES = [768, 768]


def finalize_winner(result, args, *, repo_root, manifest, judge, client,
                    blender_runner=None, repaint=None):
    """Texture the loop's winning mesh (auto-repaint bake), re-judge informational, emit textured GLB
    + sidecar, print a retry command. Returns the routed textured GLB Path, or None when skipped or
    failed. Non-fatal by contract: a texturing/judge hiccup never loses the already-good shape."""
    if not getattr(args, "finalize", False) or getattr(args, "pipeline", None) != "mesh3d":
        return None
    if blender_runner is None:
        blender_runner = _blender.run_template
    if repaint is None:
        repaint = finalize_core.repaint_views
    repo_root = Path(repo_root)

    if result.best_image is None:
        print("[finalize] no winning shape to texture (loop produced no render); skipping",
              file=sys.stderr)
        return None
    sheet = Path(result.best_image)
    side = sheet.with_name(sheet.stem + RENDER_TEXTURE_SUFFIX)
    if not side.exists():
        print(f"[finalize] winner sidecar {side.name} missing; emitting untextured winner",
              file=sys.stderr)
        return None
    info = json.loads(side.read_text(encoding="utf-8"))
    glb = (sheet.parent / info["glb"]).resolve()
    concept = (sheet.parent / info["concept"]).resolve()
    seed = int(info.get("seed", 0))
    palette = list(getattr(manifest, "palette", []) or [])
    views = max(1, min(7, int(getattr(args, "finalize_views", 4))))
    azimuths = [360.0 * i / views for i in range(views)]
    texture_res = int(getattr(args, "texture_res", 1024))
    tmp = Path(tempfile.mkdtemp(prefix="chimera_finalize_"))

    # Critical path: generate views -> bake -> route the textured GLB. Any failure here leaves the
    # untextured winner untouched (return None) — never crash an otherwise-successful run.
    try:
        view_paths, azimuths = repaint(
            client, mesh=glb, concept=concept, subject=args.subject, azimuths=azimuths,
            comfy_output_dir=args.comfy_output_dir, repo_root=repo_root,
            blender_runner=blender_runner, seed=seed, res=texture_res, elevation=_ELEVATION,
            cn_strength=_CN_STRENGTH, ip_weight=_IP_WEIGHT, blender_bin=args.blender_bin)
        params = finalize_core.finalize_params(
            mesh=str(glb), view_paths=view_paths, azimuths=azimuths, brand=args.brand, seed=seed,
            elevation=_ELEVATION, back_fill="palette", palette=palette, texture_res=texture_res,
            samples=_SAMPLES, res=_RES, out_dir=str(tmp))
        template = repo_root / "workflows" / "templates" / "blender" / finalize_core.FINALIZE_TEMPLATE
        mani = blender_runner(template, params, blender_bin=args.blender_bin,
                              timeout=finalize_core.FINALIZE_TIMEOUT)
        glb_out = mani.get("textured_glb")
        if not glb_out:
            raise finalize_core.FinalizeError("bake produced no textured GLB")
        routed_glb = route_output(repo_root, args.brand, Path(glb_out), "finalize", seed)
    except Exception as e:   # noqa: BLE001 — finalize is best-effort; keep the untextured winner
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[finalize] texturing failed ({e}); emitting untextured winner", file=sys.stderr)
        return None

    # Verification sheet + re-judge are niceties (informational): their failure must NOT lose the GLB.
    verdict, routed_sheet = None, None
    try:
        sheet_tmp = tmp / "texture_sheet.png"
        montage.contact_sheet([Path(s) for s in mani.get("outputs", [])], sheet_tmp, cols=2)
        rubric = build_rubric(manifest, args.subject, modality="3d", textured=True)
        verdict = judge.judge(str(sheet_tmp), rubric)
        routed_sheet = route_output(repo_root, args.brand, sheet_tmp, "finalize", seed)
    except Exception as e:   # noqa: BLE001
        print(f"[finalize] verification/re-judge skipped ({e})", file=sys.stderr)
    shutil.rmtree(tmp, ignore_errors=True)

    outs = [routed_glb] + ([routed_sheet] if routed_sheet else [])
    params_meta = {"concept": concept.name, "views": [Path(v).name for v in view_paths],
                   "azimuths": azimuths, "cn_strength": _CN_STRENGTH, "ip_weight": _IP_WEIGHT,
                   "seed": seed, "texture_score": getattr(verdict, "score", None),
                   "texture_passed": getattr(verdict, "passed", None),
                   "texture_issues": getattr(verdict, "issues", None)}
    meta = build_render_meta(mode="finalize", brand=args.brand, seed=seed,
                             template=finalize_core.FINALIZE_TEMPLATE, params=params_meta,
                             outputs=[p.name for p in outs], source=glb.name,
                             blender_version=mani.get("blender_version"),
                             timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
                             pipeline_git_sha=git_provenance(repo_root))
    write_sidecar(routed_glb, meta)

    score = getattr(verdict, "score", None)
    print(f"[finalize] textured winner -> {routed_glb}  (texture score={score})")
    brand_flag = f"--brand {args.brand} " if args.brand else ""
    print("[finalize] not happy with the texture? retry by hand with a new seed:\n"
          f"  python scripts/generate.py finalize-texture --auto-repaint {brand_flag}"
          f"--from {routed_glb} --concept {concept} --subject \"{args.subject}\" "
          f"--seed {seed + 1} --comfy-output-dir {args.comfy_output_dir}")
    return routed_glb
