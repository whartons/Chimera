"""Sub-brands: `--brand family/name` groups related brands (one organisation's trophies, medals, certificates...)
under brands/<family>/<name>/, each with its own brand.yaml. File names stay flat: a sub-brand's renders are named
`family-name_<mode>_<seed>`, so a brand moved into a family keeps the file names it already had."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pytest
import scripts.brandkit.outputs as outputs


@pytest.mark.parametrize("name", ["acme/medals", "Timber PTA/certs", "Café & Co/east", "a.b/c-d"])
def test_a_family_and_a_name_is_a_brand(name):
    assert outputs.brand_name_ok(name) is True


@pytest.mark.parametrize("name", ["a/b/c", "/a", "a/", "a//b", "../a", "a/..", "./a", "a/.", "a/.hidden",
                                  ".fam/a", "a/b\\c", "a\\b", "c:/x", "a/what?", "a/ b", "a/b.", "fam/bell\x07"])
def test_a_sub_brand_is_still_two_plain_folder_names(name):
    assert outputs.brand_name_ok(name) is False


@pytest.mark.parametrize("brand, stem", [("acme", "acme"), ("acme/medals", "acme-medals"),
                                         ("Timber PTA/certs", "Timber PTA-certs")])
def test_the_file_name_stem_of_a_brand_is_flat(brand, stem):
    assert outputs.brand_stem(brand) == stem


def test_a_sub_brand_renders_inside_its_family_with_the_flat_name(tmp_path):
    src = tmp_path / "comfy" / "x.png"
    src.parent.mkdir(); src.write_bytes(b"png")
    dest = outputs.route_output(tmp_path, "acme/medals", src, "txt2img", 7)
    assert dest == tmp_path / "brands" / "acme" / "medals" / "outputs" / "images" / "acme-medals_txt2img_7.png"
    assert dest.read_bytes() == b"png"


def test_a_sub_brand_job_stem_is_flat(tmp_path):
    assert outputs.job_stem(tmp_path, "acme/medals", ["a.step", "a.stl"], "cad", 3) == "acme-medals_cad_3"


def test_a_flat_brand_routes_exactly_as_before(tmp_path):
    src = tmp_path / "x.png"; src.write_bytes(b"png")
    dest = outputs.route_output(tmp_path, "acme-medals", src, "txt2img", 7)
    assert dest == tmp_path / "brands" / "acme-medals" / "outputs" / "images" / "acme-medals_txt2img_7.png"


# --- new-brand / lint -------------------------------------------------------------------------------------
def _template(root):
    tpl = root / "brands" / "_template"
    tpl.mkdir(parents=True)
    (tpl / "brand.yaml").write_text('name: "Your Brand"\ndefaults: { model: "x.safetensors" }\n'
                                    'logo: { default: null }\n', encoding="utf-8")


def test_new_brand_creates_a_sub_brand_inside_its_family(tmp_path):
    from scripts.brandkit.manifest import load_manifest
    from scripts.brandkit.scaffold import new_brand
    _template(tmp_path)
    dest = new_brand(tmp_path, "acme/medals")
    assert dest == tmp_path / "brands" / "acme" / "medals"
    assert load_manifest(dest / "brand.yaml").name == "acme/medals"


def test_new_brand_adds_a_sub_brand_beside_existing_ones(tmp_path):
    from scripts.brandkit.scaffold import new_brand
    _template(tmp_path)
    new_brand(tmp_path, "acme/medals")
    new_brand(tmp_path, "acme/certs")
    assert sorted(p.name for p in (tmp_path / "brands" / "acme").iterdir()) == ["certs", "medals"]
    with pytest.raises(FileExistsError):
        new_brand(tmp_path, "acme/medals")


def test_lint_reads_a_sub_brand(tmp_path):
    from scripts.brandkit.scaffold import lint_brand
    d = tmp_path / "brands" / "acme" / "medals"
    d.mkdir(parents=True)
    (d / "brand.yaml").write_text('name: "Acme medals"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                                  'logo: { default: null }\n', encoding="utf-8")
    res = lint_brand(tmp_path, "acme/medals")
    assert not any(lvl == "fail" for lvl, _ in res) and any("Acme medals" in m for _, m in res)


# --- replay -----------------------------------------------------------------------------------------------
def test_replay_accepts_a_sub_brand_sidecar():
    from scripts.generate import _args_from_sidecar
    s = {"schema": 2, "kind": "generate", "modality": "image", "mode": "txt2img", "brand": "acme/medals",
         "seed": 5, "watermark": False, "inputs": {"subject": "x"}}
    assert _args_from_sidecar(s).brand == "acme/medals"


# --- the Blender / FreeCAD / finalize / agent / training names --------------------------------------------
def test_dcc_render_and_cad_stems_are_flat():
    import scripts.brandkit.dcc_cli as G
    r = argparse.Namespace(modality="render", brand="acme/medals", seed=7, from_="m.glb", mode="mesh", samples=8,
                           res=[64, 64], turntable=False, frames=72, as_="backdrop", target_tris=1000,
                           watertight=False, solid=False, scale_mm=None, color="material", formats="stl",
                           render_still=True, project_image=None, blender_bin=None, timeout=None)
    assert G._render_params(r, "/x/m.glb", Path("/tmp/w"), 7)["stem"] == "acme-medals_mesh_7"
    c = argparse.Namespace(modality="cad", brand="acme/medals", seed=5, mode="primitive", shape="box",
                           length=4.0, width=3.0, height=2.0, radius=1.0, radius2=0.0, inner_radius=0.5,
                           from_=None, script=None, formats="stl", freecad_bin=None, timeout=None)
    assert G._cad_params(c, None, Path("/tmp/w"), 5)["stem"] == "acme-medals_primitive_5"


def test_finalize_stem_is_flat():
    import scripts.brandkit.finalize as F
    p = F.finalize_params(mesh="m", view_paths=[], azimuths=[], brand="acme/medals", seed=3, elevation=15.0,
                          back_fill="palette", palette=[], texture_res=1024, samples=8, res=[64, 64], out_dir="/t")
    assert p["stem"] == "acme-medals_3"


def test_the_render_loop_stem_is_flat(monkeypatch, tmp_path):
    import scripts.agent.render_generate as rg
    seen = {}
    monkeypatch.setattr(rg.image_filler, "build", lambda *a, **k: {"g": "txt2img"})
    monkeypatch.setattr(rg.threed_filler, "build", lambda *a, **k: {"g": "mesh"})
    monkeypatch.setattr(rg, "run_graph_to_file", lambda c, wf, out, **k: Path(out) / (
        "concept.png" if wf.get("g") == "txt2img" else "mesh.glb"))

    def route(root, brand, src, mode, seed, **kw):
        d = tmp_path / "routed" / f"{mode}_{seed}{Path(src).suffix}"
        d.parent.mkdir(parents=True, exist_ok=True); d.write_text("x"); return d
    monkeypatch.setattr(rg, "route_output", route)

    def runner(template, params, **kw):
        seen["stem"] = params["stem"]
        return {"outputs": [str(Path(params["out_dir"]) / f"v{i}.png") for i in range(4)], "checks": {}}
    monkeypatch.setattr(rg.montage, "contact_sheet", lambda p, out, **k: Path(out).write_text("s") or Path(out))

    class Client:
        def upload_image(self, p): return "u"
        def queue_prompt(self, wf): return "pid"
        def wait(self, pid, max_wait=None): return None
    a = argparse.Namespace(brand="acme/medals", comfy_output_dir="/c", from_image=None, octree=256, samples=8,
                           res=[64, 64], variant=None, model=None, blender_bin=None, timeout=None)
    rg.make_render_generate(a, tmp_path, manifest=object(), client=Client(), blender_runner=runner)("x", "", 7)
    assert "/" not in seen["stem"] and seen["stem"].startswith("acme-medals_")


def test_the_cad_loop_stem_is_flat(monkeypatch, tmp_path):
    import scripts.agent.cad_generate as CG
    seen = {}

    class Gen:
        prev = None
        def generate_script(self, brief, fix_feedback=None): return "box = 1"

    def fc(tmpl, params, **kw):
        seen["stem"] = params["stem"]
        stl = Path(params["out_dir"]) / "m.stl"; stl.write_text("stl"); return {"outputs": [str(stl)]}

    def bl(tmpl, params, **kw):
        outs = []
        for i in range(4):
            p = Path(params["out_dir"]) / f"v{i}.png"; p.write_text("p"); outs.append(str(p))
        return {"outputs": outs}
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda p, out, **k: Path(out).write_text("s") or Path(out))

    def route(root, brand, src, mode, seed, **kw):
        d = tmp_path / "routed" / f"{mode}_{seed}{Path(src).suffix}"
        d.parent.mkdir(parents=True, exist_ok=True); d.write_text("x"); return d
    monkeypatch.setattr(CG, "route_output", route)
    a = argparse.Namespace(brand="acme/medals", subject="a mug", samples=8, res=[64, 64], freecad_bin=None,
                           blender_bin=None, freecad_timeout=None, blender_timeout=None)
    CG.make_cad_generate(a, tmp_path, Gen(), freecad_runner=fc, blender_runner=bl)("P", "", 5)
    assert "/" not in seen["stem"] and seen["stem"].startswith("acme-medals_")


def test_lora_training_names_are_flat_for_a_sub_brand(tmp_path, monkeypatch):
    from scripts import train_brand_lora as T
    b = tmp_path / "brands" / "acme" / "medals"
    (b / "training").mkdir(parents=True)
    (b / "brand.yaml").write_text('name: "Acme medals"\n', encoding="utf-8")
    (b / "training" / "img.png").write_bytes(b"x")
    (b / "training" / "img.txt").write_text("a caption", encoding="utf-8")
    monkeypatch.setattr(T.subprocess, "run", lambda *a, **k: pytest.fail("dry-run"))
    T.main(["--brand", "acme/medals"], repo_root=tmp_path)
    cfg = json.loads((b / "lora" / "acme-medals-train-config.json").read_text(encoding="utf-8"))
    assert cfg["dataset_dir"] == "brands/acme/medals/training" and cfg["output_dir"] == "brands/acme/medals/lora"
    assert cfg["output_name"] == "acme-medals-v1" and cfg["trigger_word"] == "acme medals"
