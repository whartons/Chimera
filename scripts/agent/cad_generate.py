"""The autonomous CAD self-correction generator (#1): an LLM writes/revises a FreeCAD script -> `cad
--mode script` executes it to an STL -> headless Blender renders a 4-view contact sheet for the judge.
Returns a generate(pos, neg, seed) closure with the same signature run_loop's other generators use, so
the model-free loop core is reused unchanged. No ComfyUI in the loop unless the judge is the Qwen backend
(the LLM judge / --backend api makes it a pure LLM+FreeCAD+Blender loop). pos carries the subject + the
expander's accumulated FIX feedback; the LLMCadGenerator revises its previous script from it."""
from __future__ import annotations
import re, shutil, tempfile
from pathlib import Path

from scripts.brandkit import montage
from scripts.brandkit.outputs import route_output
from scripts.brandkit.freecad import run_template as fc_run
from scripts.brandkit.blender import run_template as bl_run

_FC_TIMEOUT = 600
_BL_TIMEOUT = 1800

# A FreeCAD modelling script needs none of these. The autonomous loop execs LLM-authored scripts
# (unlike `cad --mode script` where a human authored it), so a bad/jailbroken generation must not get
# shell/network/filesystem-delete reach. A denylist is not a sandbox (FreeCAD has its own file I/O), but
# it stops the obvious footguns; a rejected script just fails that iteration and the loop retries.
_FORBIDDEN = re.compile(
    r"\b(subprocess|socket|shutil\s*\.\s*rmtree|os\s*\.\s*system|os\s*\.\s*popen|os\s*\.\s*remove|"
    r"os\s*\.\s*unlink|os\s*\.\s*rmdir|requests|urllib|httpx|http\.client|__import__|eval\s*\(|exec\s*\()")


def _assert_safe(script: str):
    m = _FORBIDDEN.search(script)
    if m:
        raise RuntimeError(f"LLM CAD script rejected — disallowed operation {m.group(0)!r}; "
                           "autonomous scripts may only do FreeCAD modelling (no shell/network/delete)")


def make_cad_generate(args, repo_root, generator, *, freecad_runner=fc_run, blender_runner=bl_run):
    """Build the loop's generate(pos, neg, seed) -> routed-contact-sheet-path closure."""
    repo_root = Path(repo_root)
    script_tmpl = repo_root / "workflows" / "templates" / "freecad" / "script_exec.py"
    eval_tmpl = repo_root / "workflows" / "templates" / "blender" / "mesh_eval.py"
    fc_timeout = getattr(args, "freecad_timeout", None) or _FC_TIMEOUT
    bl_timeout = getattr(args, "blender_timeout", None) or _BL_TIMEOUT

    def generate(pos, neg, seed):
        # 1. code-gen: the LLM writes/revises a FreeCAD script for `pos` (subject + accumulated FIX).
        script = generator.generate_script(pos)
        _assert_safe(script)   # the autonomous loop execs LLM-authored scripts — reject obvious footguns
        tmp = Path(tempfile.mkdtemp(prefix="chimera_cad_loop_"))
        try:
            stem = f"{args.brand or 'cad'}_{seed}"
            sp = tmp / "model.py"
            sp.write_text(script, encoding="utf-8")
            # 2. execute it headless -> STL (FreeCAD)
            cad_mani = freecad_runner(script_tmpl,
                                      {"script": str(sp), "out_dir": str(tmp), "stem": stem, "formats": ["stl"]},
                                      freecad_bin=args.freecad_bin, timeout=fc_timeout)
            stl = next((o for o in cad_mani.get("outputs", []) if str(o).lower().endswith(".stl")), None)
            if not stl:
                raise RuntimeError("cad code-gen produced no STL")
            # 3. render a 4-view contact sheet (Blender) for the judge
            mani = blender_runner(eval_tmpl,
                                  {"mesh": str(Path(stl).resolve()), "out_dir": str(tmp), "stem": stem,
                                   "samples": args.samples, "res": list(args.res), "seed": seed, "views": 4},
                                  blender_bin=args.blender_bin, timeout=bl_timeout)
            stills = mani.get("outputs", [])
            sheet_tmp = tmp / "sheet.png"
            montage.contact_sheet([Path(s) for s in stills], sheet_tmp, cols=2)
            # 4. route the judged sheet + the STL artifact out of tmp before cleanup
            sheet = route_output(repo_root, args.brand, sheet_tmp, "cad", seed)
            route_output(repo_root, args.brand, Path(stl), "cad", seed)
            # keep the winning script beside the sheet for reproducibility/inspection
            (Path(sheet).with_name(Path(sheet).stem + ".cad.py")).write_text(script, encoding="utf-8")
            return str(sheet)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return generate
