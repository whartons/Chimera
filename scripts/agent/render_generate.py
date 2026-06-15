"""The 3D self-correction generator: subject -> concept image -> Hunyuan3D mesh -> Blender
mesh_eval (4 orbit stills + bmesh geometry checks) -> host-side contact sheet -> return the sheet
path for the judge. Mesh GENERATION stays in ComfyUI (Hunyuan3D is image-conditioned); Blender only
renders + probes. Returns a generate(pos, neg, seed) closure with the same signature the loop's
image generator uses, so run_loop is untouched. The geometry facts ride a '<stem>.checks.json'
sidecar that GeometryAwareJudge reads."""
from __future__ import annotations
import json, shutil, tempfile
from pathlib import Path

from scripts.brandkit import workflow as image_filler
from scripts.brandkit import threed as threed_filler
from scripts.brandkit import montage
from scripts.brandkit.outputs import select_output, route_output
from scripts.brandkit.blender import run_template
from scripts.agent.geometry import RENDER_CHECKS_SUFFIX

_MESH_EVAL = "mesh_eval.py"
_BLENDER_TIMEOUT = 1800  # mesh render + 4 stills + bmesh probe
RENDER_TEXTURE_SUFFIX = ".texture.json"


def make_render_generate(args, repo_root, manifest, client, *, blender_runner=run_template):
    """Build the loop's generate(pos, neg, seed) -> routed-contact-sheet-path closure."""
    repo_root = Path(repo_root)
    out_dir = Path(args.comfy_output_dir)
    template = repo_root / "workflows" / "templates" / "blender" / _MESH_EVAL
    # Two independent budgets: --timeout caps each ComfyUI wait; the Blender job (mesh render +
    # 4 stills) gets its own --blender-timeout so tuning the ComfyUI wait can't starve the render.
    comfy_timeout = args.timeout or 900
    blender_timeout = getattr(args, "blender_timeout", None) or _BLENDER_TIMEOUT
    # Texture settings are fixed for the whole loop — resolve once (getattr-guarded so lean test
    # namespaces / partial args still work), not per generate() call.
    texture = bool(getattr(args, "texture", False))
    back_fill = getattr(args, "back_fill", "palette")
    texture_res = int(getattr(args, "texture_res", 1024))
    palette = list(getattr(manifest, "palette", []) or [])

    def _concept(pos, neg, seed):
        """Stage A: produce the concept image; return (uploaded_name, local_path). The uploaded
        name conditions Hunyuan3D; the local path is the texture source for the Phase-4a bake.
        With --from-image, upload the fixed concept directly and skip txt2img."""
        if args.from_image:
            local = Path(args.from_image)
            return client.upload_image(local), local
        wf = image_filler.build(repo_root, manifest, positive=pos, negative=neg, seed=seed,
                                mode="txt2img", variant=args.variant, model=args.model)
        pid = client.queue_prompt(wf)
        client.wait(pid, max_wait=comfy_timeout)
        fname, subfolder, _ = select_output(client, pid, wf)
        local = out_dir / subfolder / fname
        return client.upload_image(local), local

    def generate(pos, neg, seed):
        # Expensive: one txt2img graph (unless --from-image) + one Hunyuan3D mesh graph + one
        # headless Blender render per call. A single iteration can take minutes — the loop's
        # --max-iters defaults to 3 for mesh3d for this reason.
        uploaded, concept_path = _concept(pos, neg, seed)

        # Stage B: Hunyuan3D mesh. Leave the GLB in the ComfyUI output dir; only route it after the
        # render succeeds, so a failed Blender job doesn't orphan a meshless GLB in outputs/3d.
        wf3d = threed_filler.build(repo_root, manifest, from_image=uploaded, seed=seed,
                                   octree=args.octree, model=args.model)
        pid = client.queue_prompt(wf3d)
        client.wait(pid, max_wait=comfy_timeout)
        gname, gsub, _ = select_output(client, pid, wf3d)
        glb_src = out_dir / gsub / gname

        # Stage C: render 4 orbit stills + geometry checks (+ Phase-4a: bake + textured GLB).
        tmp = Path(tempfile.mkdtemp(prefix="chimera_eval_"))
        try:
            stem = f"{args.brand or 'agent'}_{seed}"
            mani = blender_runner(
                template,
                {"mesh": str(glb_src.resolve()), "out_dir": str(tmp), "stem": stem,
                 "samples": args.samples, "res": list(args.res), "seed": seed, "views": 4,
                 "texture": texture, "asset": str(Path(concept_path).resolve()),
                 "back_fill": back_fill, "palette": palette, "texture_res": texture_res},
                blender_bin=args.blender_bin, timeout=blender_timeout)
            stills = mani.get("outputs", [])
            checks = mani.get("checks", {})

            # Stage D: montage the 4 stills into one contact sheet (in tmp).
            sheet_tmp = tmp / "sheet.png"
            montage.contact_sheet([Path(s) for s in stills], sheet_tmp, cols=2)
            # Stage E: render succeeded — route the mesh (textured GLB if present, else raw) + sheet.
            glb_out = mani.get("textured_glb") or str(glb_src)
            glb_dest = route_output(repo_root, args.brand, Path(glb_out), "agent", seed)
            sheet = route_output(repo_root, args.brand, sheet_tmp, "agent", seed)

            # Stage F: geometry-check sidecar (Phase 3) + texture-status sidecar (Phase 4a). The
            # texture sidecar records the routed GLB name so Phase 4b can find the mesh to finalize.
            cf = Path(sheet).with_name(Path(sheet).stem + RENDER_CHECKS_SUFFIX)
            cf.write_text(json.dumps(checks), encoding="utf-8")
            # Always record the winner's mesh + concept (+ seed) so Phase 4b in-loop finalize can
            # recover them — not just under --texture. Route a concept copy so the sidecar is
            # self-contained (the txt2img/from-image source can otherwise be cleaned away).
            concept_dest = route_output(repo_root, args.brand, Path(concept_path), "concept", seed)
            tf = Path(sheet).with_name(Path(sheet).stem + RENDER_TEXTURE_SUFFIX)
            tf.write_text(json.dumps({"textured": bool(mani.get("textured")),
                                      "glb": Path(glb_dest).name,
                                      "concept": Path(concept_dest).name,
                                      "seed": seed}), encoding="utf-8")
            return str(sheet)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return generate
