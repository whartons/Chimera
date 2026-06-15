import argparse, json
from pathlib import Path
from scripts.agent.judge import Verdict
from scripts.agent.loop import LoopResult
from scripts.brandkit.manifest import default_manifest
import scripts.agent.finalize as FIN


class _Judge:
    def __init__(self, verdict): self.verdict = verdict; self.seen = []
    def judge(self, image, rubric): self.seen.append((image, rubric)); return self.verdict


def _args(**kw):
    base = dict(finalize=True, pipeline="mesh3d", brand=None, subject="a rover",
                comfy_output_dir="/comfy/out", finalize_views=4, texture_res=1024, blender_bin=None)
    base.update(kw); return argparse.Namespace(**base)


def _winner(tmp_path, *, textured=False, seed=7):
    """Mirror the real render_generate layout: sheet+concept route to outputs/images/, the GLB to
    outputs/3d/ (a DIFFERENT dir), and the sidecar (next to the sheet) records ABSOLUTE glb/concept
    paths. This cross-dir layout guards the bug where the GLB was sought beside the sheet."""
    img = tmp_path / "outputs" / "images"; img.mkdir(parents=True, exist_ok=True)
    td = tmp_path / "outputs" / "3d"; td.mkdir(parents=True, exist_ok=True)
    sheet = img / "agent_7.png"; sheet.write_text("sheet")
    glb = td / "agent_7.glb"; glb.write_text("mesh")
    concept = img / "concept_7.png"; concept.write_text("img")
    side = sheet.with_name(sheet.stem + FIN.RENDER_TEXTURE_SUFFIX)
    side.write_text(json.dumps({"textured": textured, "glb": str(glb),
                                "concept": str(concept), "seed": seed}))
    return sheet


def _wire(monkeypatch, tmp_path):
    """Stub the module-level seams (route/montage/provenance). Returns a `calls` dict."""
    calls = {"routed": []}
    monkeypatch.setattr(FIN.montage, "contact_sheet",
                        lambda paths, out, **k: Path(out).write_text("ts") or Path(out))
    monkeypatch.setattr(FIN, "git_provenance", lambda r: "deadbee")

    def fake_route(root, brand, src, mode, seed, **kw):
        d = Path(root) / "outputs" / "3d" / f"{mode}_{seed}{Path(src).suffix}"
        d.parent.mkdir(parents=True, exist_ok=True); d.write_text("x")
        calls["routed"].append(d); return d

    monkeypatch.setattr(FIN, "route_output", fake_route)
    return calls


def test_finalize_winner_happy_branded(monkeypatch, tmp_path):
    sheet = _winner(tmp_path)
    _wire(monkeypatch, tmp_path)

    def fake_repaint(client, **kw):
        return [Path(tmp_path / "rp0.png"), Path(tmp_path / "rp1.png")], list(kw["azimuths"])

    def fake_bl(template, params, **kw):
        assert Path(template).name == "mesh_finalize.py"
        tglb = Path(params["out_dir"]) / "textured.glb"; tglb.write_text("g")
        return {"textured_glb": str(tglb), "outputs": [], "blender_version": "5.1.2"}

    res = LoopResult(best_image=str(sheet), best_verdict=None, passed=True, history=[])
    out = FIN.finalize_winner(res, _args(), repo_root=tmp_path, manifest=default_manifest(),
                              judge=_Judge(Verdict(passed=True, score=0.88, issues=[])),
                              client=object(), blender_runner=fake_bl, repaint=fake_repaint)
    assert out is not None and out.suffix == ".glb"
    side = out.with_suffix(".json")          # finalize sidecar next to the textured GLB
    meta = json.loads(side.read_text())
    assert meta["mode"] == "finalize" and meta["params"]["texture_score"] == 0.88
    assert meta["params"]["seed"] == 7 and meta["source"] == "agent_7.glb"


def test_finalize_winner_brandless_routes_global_and_omits_brand_in_retry(monkeypatch, tmp_path, capsys):
    sheet = _winner(tmp_path)
    _wire(monkeypatch, tmp_path)
    fake_repaint = lambda client, **kw: ([Path(tmp_path / "rp0.png")], list(kw["azimuths"]))

    def fake_bl(template, params, **kw):
        tglb = Path(params["out_dir"]) / "t.glb"; tglb.write_text("g")
        return {"textured_glb": str(tglb), "outputs": [], "blender_version": "5.1.2"}

    res = LoopResult(best_image=str(sheet), best_verdict=None, passed=True, history=[])
    out = FIN.finalize_winner(res, _args(brand=None, finalize_views=1), repo_root=tmp_path,
                              manifest=default_manifest(),
                              judge=_Judge(Verdict(passed=True, score=0.7, issues=[])),
                              client=object(), blender_runner=fake_bl, repaint=fake_repaint)
    assert out is not None
    printed = capsys.readouterr().out
    assert "--brand" not in printed                       # brandless retry command
    assert "finalize-texture --auto-repaint" in printed


def test_finalize_winner_missing_sidecar_returns_none(monkeypatch, tmp_path):
    out = tmp_path / "outputs" / "3d"; out.mkdir(parents=True)
    sheet = out / "agent_7.png"; sheet.write_text("sheet")     # no .texture.json beside it
    _wire(monkeypatch, tmp_path)
    res = LoopResult(best_image=str(sheet), best_verdict=None, passed=False, history=[])
    assert FIN.finalize_winner(res, _args(), repo_root=tmp_path, manifest=default_manifest(),
                               judge=_Judge(Verdict(True, 1.0, [])), client=object(),
                               blender_runner=lambda *a, **k: {}, repaint=lambda *a, **k: ([], [])) is None


def test_finalize_winner_repaint_failure_is_nonfatal(monkeypatch, tmp_path):
    sheet = _winner(tmp_path)
    _wire(monkeypatch, tmp_path)

    def boom(client, **kw):
        raise RuntimeError("comfy down")

    res = LoopResult(best_image=str(sheet), best_verdict=None, passed=True, history=[])
    assert FIN.finalize_winner(res, _args(), repo_root=tmp_path, manifest=default_manifest(),
                               judge=_Judge(Verdict(True, 1.0, [])), client=object(),
                               blender_runner=lambda *a, **k: {}, repaint=boom) is None


def test_finalize_winner_no_winner_skips(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    res = LoopResult(best_image=None, best_verdict=None, passed=False, history=[])
    assert FIN.finalize_winner(res, _args(), repo_root=tmp_path, manifest=default_manifest(),
                               judge=_Judge(Verdict(False, 0.0, [])), client=object(),
                               blender_runner=lambda *a, **k: {}, repaint=lambda *a, **k: ([], [])) is None


def test_finalize_winner_skips_when_flag_off(tmp_path):
    res = LoopResult(best_image="x.png", best_verdict=None, passed=True, history=[])
    assert FIN.finalize_winner(res, _args(finalize=False), repo_root=tmp_path,
                               manifest=default_manifest(), judge=_Judge(Verdict(True, 1.0, [])),
                               client=object()) is None
