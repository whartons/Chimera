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
    """Create a routed sheet + its .texture.json sidecar + the referenced glb/concept siblings."""
    out = tmp_path / "outputs" / "3d"; out.mkdir(parents=True, exist_ok=True)
    sheet = out / "agent_7.png"; sheet.write_text("sheet")
    (out / "agent_7.glb").write_text("mesh")
    (out / "concept_7.png").write_text("img")
    side = sheet.with_name(sheet.stem + FIN.RENDER_TEXTURE_SUFFIX)
    side.write_text(json.dumps({"textured": textured, "glb": "agent_7.glb",
                                "concept": "concept_7.png", "seed": seed}))
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
