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

# The autonomous loop execs LLM-authored scripts (unlike `cad --mode script`, which a human authored).
# Two layers guard that: this regex pre-filter rejects obvious escapes early, AND script_exec.py runs the
# script with restricted builtins + an import allowlist (restrict=True below). NEITHER is a true sandbox —
# FreeCAD's own API (Mesh.export / doc.saveAs) can still write files — so this is a best-effort speed bump,
# NOT a security boundary: only point --pipeline cad at an LLM you trust, on a machine you accept it
# touching. A rejected script just fails that iteration and the loop retries.
_FORBIDDEN = re.compile(
    r"\b(subprocess|socket|importlib|shutil\s*\.\s*rmtree|os\s*\.\s*(system|popen|remove|unlink|rmdir|"
    r"startfile|environ)|requests|urllib|httpx|http\.client|__import__|eval\s*\(|exec\s*\(|open\s*\(|"
    r"getattr\s*\(|\.\s*unlink\s*\()")


def _assert_safe(script: str):
    m = _FORBIDDEN.search(script)
    if m:
        raise RuntimeError(f"LLM CAD script rejected — disallowed operation {m.group(0).strip()!r}; "
                           "autonomous scripts may only do FreeCAD modelling (no shell/network/file ops)")


def make_cad_generate(args, repo_root, generator, *, freecad_runner=fc_run, blender_runner=bl_run):
    """Build the loop's generate(pos, neg, seed) -> routed-contact-sheet-path closure."""
    repo_root = Path(repo_root)
    script_tmpl = repo_root / "workflows" / "templates" / "freecad" / "script_exec.py"
    eval_tmpl = repo_root / "workflows" / "templates" / "blender" / "mesh_eval.py"
    fc_timeout = getattr(args, "freecad_timeout", None) or _FC_TIMEOUT
    bl_timeout = getattr(args, "blender_timeout", None) or _BL_TIMEOUT
    state = {"first": True, "last_good": None}   # carry revision state across iterations

    def generate(pos, neg, seed):
        # 1. code-gen. Brief = the clean subject; the loop's FIX directives (folded into `pos` by the
        # expander) are passed as explicit revision feedback once we have a prior script to revise.
        feedback = None if state["first"] else pos
        script = generator.generate_script(args.subject, fix_feedback=feedback)
        state["first"] = False
        try:
            _assert_safe(script)   # the loop execs LLM-authored scripts — reject obvious escapes
        except RuntimeError:
            generator.prev = state["last_good"]   # don't let a rejected script seed the next revision
            raise
        state["last_good"] = script
        tmp = Path(tempfile.mkdtemp(prefix="chimera_cad_loop_"))
        try:
            stem = f"{args.brand or 'cad'}_{seed}"
            sp = tmp / "model.py"
            sp.write_text(script, encoding="utf-8")
            # 2. execute it headless -> STL (FreeCAD), with restricted builtins + import allowlist
            cad_mani = freecad_runner(script_tmpl,
                                      {"script": str(sp), "out_dir": str(tmp), "stem": stem,
                                       "formats": ["stl"], "restrict": True},
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
