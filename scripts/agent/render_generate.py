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


def make_render_generate(args, repo_root, manifest, client, *, blender_runner=run_template):
    """Build the loop's generate(pos, neg, seed) -> routed-contact-sheet-path closure."""
    repo_root = Path(repo_root)
    out_dir = Path(args.comfy_output_dir)
    template = repo_root / "workflows" / "templates" / "blender" / _MESH_EVAL
    comfy_timeout = args.timeout or 900

    def _concept(pos, neg, seed):
        """Stage A: produce the concept image and return the ComfyUI-uploaded name to condition
        Hunyuan3D. With --from-image, skip txt2img and upload the fixed concept directly."""
        if args.from_image:
            return client.upload_image(Path(args.from_image))
        wf = image_filler.build(repo_root, manifest, positive=pos, negative=neg, seed=seed,
                                mode="txt2img", variant=args.variant, model=args.model)
        pid = client.queue_prompt(wf)
        client.wait(pid, max_wait=comfy_timeout)
        fname, subfolder, _ = select_output(client, pid, wf)
        return client.upload_image(out_dir / subfolder / fname)

    def generate(pos, neg, seed):
        uploaded = _concept(pos, neg, seed)

        # Stage B: image-conditioned Hunyuan3D mesh; route the GLB into outputs/3d.
        wf3d = threed_filler.build(repo_root, manifest, from_image=uploaded, seed=seed,
                                   octree=args.octree, model=args.model)
        pid = client.queue_prompt(wf3d)
        client.wait(pid, max_wait=comfy_timeout)
        gname, gsub, _ = select_output(client, pid, wf3d)
        glb = route_output(repo_root, args.brand, out_dir / gsub / gname, "agent", seed)

        # Stage C: render 4 orbit stills + compute geometry checks (headless Blender).
        tmp = Path(tempfile.mkdtemp(prefix="chimera_eval_"))
        try:
            stem = f"{args.brand or 'agent'}_{seed}"
            mani = blender_runner(
                template,
                {"mesh": str(Path(glb).resolve()), "out_dir": str(tmp), "stem": stem,
                 "samples": args.samples, "res": list(args.res), "seed": seed, "views": 4},
                blender_bin=args.blender_bin, timeout=args.timeout or _BLENDER_TIMEOUT)
            stills = mani.get("outputs", [])
            checks = mani.get("checks", {})

            # Stage D/E: montage to a tmp sheet, then route into outputs/images.
            sheet_tmp = tmp / "sheet.png"
            montage.contact_sheet([Path(s) for s in stills], sheet_tmp, cols=2)
            sheet = route_output(repo_root, args.brand, sheet_tmp, "agent", seed)

            # Stage F: write the geometry facts next to the sheet for GeometryAwareJudge.
            cf = Path(sheet).with_name(Path(sheet).stem + RENDER_CHECKS_SUFFIX)
            cf.write_text(json.dumps(checks), encoding="utf-8")
            return str(sheet)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return generate
