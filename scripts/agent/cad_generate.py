"""The autonomous CAD self-correction generator (#1): an LLM writes/revises a FreeCAD script -> `cad
--mode script` executes it to an STL -> headless Blender renders a 4-view contact sheet for the judge.
Returns a generate(pos, neg, seed) closure with the same signature run_loop's other generators use, so
the model-free loop core is reused unchanged. No ComfyUI in the loop unless the judge is the Qwen backend
(the LLM judge / --backend api makes it a pure LLM+FreeCAD+Blender loop). pos carries the subject + the
judge's feedback (CadFeedbackExpander); the LLMCadGenerator revises its previous script from it."""
from __future__ import annotations
import json, re, shutil, tempfile
from pathlib import Path

from scripts.agent.expander import PromptExpander, brand_guard, parse_fixes
from scripts.agent.geometry import RENDER_CHECKS_SUFFIX
from scripts.agent.llm import LLMError
from scripts.agent.loop import SeedNames
from scripts.brandkit import montage  # noqa: F401 (seam: tests patch montage.contact_sheet here)
from scripts.brandkit import gpu
from scripts.brandkit.dcc import job_outputs
from scripts.brandkit.outputs import route_output
from scripts.brandkit.freecad import run_template as fc_run
from scripts.brandkit.blender import run_template as bl_run
from scripts.agent.render_generate import eval_contact_sheet

_FC_TIMEOUT = 600
_BL_TIMEOUT = 1800

# The autonomous loop execs LLM-authored scripts (unlike `cad --mode script`, which a human authored).
# Two layers guard that: this regex pre-filter rejects obvious escapes early, AND script_exec.py runs the
# script with restricted builtins + an import allowlist (restrict=True below). NEITHER is a true sandbox —
# FreeCAD's own API (Mesh.export / doc.saveAs) can still write files — so this is a best-effort speed bump,
# NOT a security boundary: only point --pipeline cad at an LLM you trust, on a machine you accept it
# touching. A rejected script just fails that iteration and the loop retries.
_FORBIDDEN = re.compile(
    # a networking/process module is out when a line imports it, not when a name merely contains the word: a
    # 'hex socket organizer' brief (a `socket` shape, '# ball-and-socket', 'from http://...' in a comment) failed
    # every iteration. Without the import the name isn't the module, and script_exec's import allowlist stops
    # `import os, socket` and the like regardless.
    r"^[ \t]*(?:import|from)[ \t]+(?:subprocess|socket|importlib|requests|urllib|httpx|http)\b"
    r"|\b(shutil\s*\.\s*rmtree|os\s*\.\s*(system|popen|remove|unlink|rmdir|"
    r"startfile|environ)|http\.client|__import__|eval\s*\(|exec\s*\(|open\s*\(|"
    r"getattr\s*\(|\.\s*unlink\s*\()"
    # introspection escapes: a function's __globals__ reached the runner's own os/import (2026-10 review),
    # as do __class__/__mro__/__subclasses__ chains and frame objects. Any dunder ATTRIBUTE but .__init__
    # is out, plus the dangerous bare names; dunder strings ('__main__') stay fine.
    r"|\.\s*__(?!init__)\w+__|\b__(builtins|loader|spec|globals|code|closure|class|dict|mro|bases|subclasses)__"
    r"|\b(f_globals|f_locals|f_back|gi_frame|tb_frame|cr_frame)\b", re.MULTILINE)


def _assert_safe(script: str):
    m = _FORBIDDEN.search(script)
    if m:
        raise RuntimeError(f"LLM CAD script rejected — disallowed operation {m.group(0).strip()!r}; "
                           "autonomous scripts may only do FreeCAD modelling (no shell/network/file ops)")


class CadFeedbackExpander(PromptExpander):
    """The loop's expander for the CAD pipeline, whose positive prompt is code-gen's revision feedback rather than
    an image prompt. The templated expander puts a judge's 'avoid X' terms only into the negative, and its NOT-MET
    reasons into the positive only when no FIX parsed, so "NOT-MET - hook arm 2 mm thick, fragile. FIX: avoid thin
    hook arm" reached code-gen as "Correct the previous attempt. a wall hook" (2026-10-25 review). This wraps the
    loop's expander and adds both to the positive: the avoid terms, and the judge's issue lines."""

    def __init__(self, inner):
        self.inner = inner

    def expand(self, subject, manifest, prior_issues=None):
        pos, neg = self.inner.expand(subject, manifest, prior_issues)
        if not prior_issues:
            return pos, neg
        _, avoid = brand_guard(*parse_fixes(prior_issues), manifest)
        found = [str(i) for i in prior_issues if str(i) not in pos]   # no-FIX issues are in it already
        if avoid:
            pos += "\nAvoid: " + ", ".join(avoid)
        if found:
            pos += "\nThe judge found:\n" + "\n".join(f"- {i}" for i in found)
        return pos, neg


def make_cad_generate(args, repo_root, generator, *, freecad_runner=fc_run, blender_runner=bl_run):
    """Build the loop's generate(pos, neg, seed) -> routed-contact-sheet-path closure."""
    repo_root = Path(repo_root)
    script_tmpl = repo_root / "workflows" / "templates" / "freecad" / "script_exec.py"
    eval_tmpl = repo_root / "workflows" / "templates" / "blender" / "mesh_eval.py"
    fc_timeout = getattr(args, "freecad_timeout", None) or _FC_TIMEOUT
    bl_timeout = getattr(args, "blender_timeout", None) or _BL_TIMEOUT
    state = {"first": True, "last_good": None}   # carry revision state across iterations
    name = SeedNames()   # a repeated seed's pass gets its own files (the winner's sheet must survive)

    def generate(pos, neg, seed):
        # 1. code-gen. Brief = the clean subject; the judge's feedback (folded into `pos` by the expander, with
        # CadFeedbackExpander's avoid terms and issue lines) is passed as explicit revision feedback once we have a
        # prior script to revise. The last run's error rides along: the loop no longer threads failures into the
        # prompt, but the codegen needs the FreeCAD traceback to fix its script. Only the script's own failures
        # count: an LLM or GPU error isn't the script's fault, and telling code-gen otherwise sent it chasing them.
        feedback = None if state["first"] else pos
        if state.get("error"):
            feedback = f"{feedback or ''}\nThe previous script failed: {state['error']}".strip()
        try:
            return _generate_once(pos, seed, feedback, name(seed))
        except LLMError:
            raise
        except Exception as exc:
            if state.get("stage") == "script":   # a Blender timeout or a locked file isn't the script's failure
                state["error"] = str(exc)[-1500:]
            raise

    def _generate_once(pos, seed, feedback, tag):
        state["stage"] = "codegen"
        script = generator.generate_script(args.subject, fix_feedback=feedback)
        # cleared only once code-gen has seen it: popped before, it was lost when code-gen failed (2026-10-25)
        state.pop("error", None)
        state["first"] = False
        # off the GPU before Blender renders (and a --backend local judge loads in ComfyUI): neither can see
        # a resident Ollama model's memory on Windows, and a 27B codegen holds about 20 GB
        client = getattr(generator, "client", None)
        if getattr(client, "release", None) is not None:
            client.release()
            if not gpu.keep_llms_loaded() and getattr(client, "resident", None) is not None and client.resident():
                # an LLMError, like the GPU's "no room": the script didn't fail, so code-gen isn't told it did
                raise LLMError(f"the code-gen model {client.model} is still loaded in Ollama, so not rendering "
                               "beside it; `python scripts/generate.py free` unloads it")
        state["stage"] = "script"   # from here to the STL, a failure is the script's (pre-filter, FreeCAD, outputs)
        try:
            _assert_safe(script)   # the loop execs LLM-authored scripts — reject obvious escapes
        except RuntimeError:
            generator.prev = state["last_good"]   # don't let a rejected script seed the next revision
            raise
        state["last_good"] = script
        tmp = Path(tempfile.mkdtemp(prefix="chimera_cad_loop_"))
        try:
            stem = f"{args.brand or 'cad'}_{tag}"
            sp = tmp / "model.py"
            sp.write_text(script, encoding="utf-8")
            # 2. execute it headless -> STL (FreeCAD), with restricted builtins + import allowlist
            cad_mani = freecad_runner(script_tmpl,
                                      {"script": str(sp), "out_dir": str(tmp), "stem": stem,
                                       "formats": ["stl"], "restrict": True},
                                      freecad_bin=args.freecad_bin, timeout=fc_timeout)
            # the LLM-written script prints on the same stdout as the manifest: take outputs from its own folder only
            stl = next((o for o in job_outputs(cad_mani, tmp, RuntimeError) if o.lower().endswith(".stl")), None)
            if not stl:
                raise RuntimeError("cad code-gen produced no STL")
            state["stage"] = "render"
            # 3. render a 4-view contact sheet (Blender) for the judge — shared eval stage
            mani, sheet_tmp = eval_contact_sheet(
                stl, tmp, stem, template=eval_tmpl, samples=args.samples, res=args.res,
                seed=seed, blender_runner=blender_runner, blender_bin=args.blender_bin,
                timeout=bl_timeout)
            # 4. route the judged sheet + the STL artifact out of tmp before cleanup
            sheet = route_output(repo_root, args.brand, sheet_tmp, "cad", tag)
            route_output(repo_root, args.brand, Path(stl), "cad", tag)
            # keep the winning script beside the sheet for reproducibility/inspection
            (Path(sheet).with_name(Path(sheet).stem + ".cad.py")).write_text(script, encoding="utf-8")
            # geometry facts beside the sheet for the loop's GeometryAwareJudge: BREP is manifold, but a
            # script can still build disconnected bodies (a VLM passed a fan rotor whose 16 blades floated
            # free of the hub, 2026-10)
            (Path(sheet).with_name(Path(sheet).stem + RENDER_CHECKS_SUFFIX)).write_text(
                json.dumps(mani.get("checks", {})), encoding="utf-8")
            return str(sheet)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return generate
