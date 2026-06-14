from pathlib import Path
from scripts.brandkit import repaint
from scripts.brandkit.nodes import find_node_by_title


def _wf(**kw):
    base = dict(depth_image="d.png", concept_image="c.png", positive="an armored rover", seed=7)
    base.update(kw)
    return repaint.build(**base)


def test_graph_has_expected_titled_nodes():
    wf = _wf()
    for title in ("brand:ckpt", "brand:positive", "brand:negative", "brand:ipmodel", "brand:clipvis",
                  "brand:concept", "brand:ipadapter", "brand:cnet", "brand:depth", "brand:cnapply",
                  "brand:latent", "brand:ksampler", "brand:decode", "brand:save"):
        find_node_by_title(wf, title)   # raises if missing


def test_model_filenames_threaded():
    wf = _wf(checkpoint="x.safetensors", ipadapter="ip.safetensors",
             clip_vision="cv.safetensors", controlnet="cn.safetensors")
    assert find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"] == "x.safetensors"
    assert find_node_by_title(wf, "brand:ipmodel")[1]["inputs"]["ipadapter_file"] == "ip.safetensors"
    assert find_node_by_title(wf, "brand:clipvis")[1]["inputs"]["clip_name"] == "cv.safetensors"
    assert find_node_by_title(wf, "brand:cnet")[1]["inputs"]["control_net_name"] == "cn.safetensors"


def test_images_routed_to_their_consumers():
    wf = _wf(depth_image="depthX.png", concept_image="conceptX.png")
    assert find_node_by_title(wf, "brand:depth")[1]["inputs"]["image"] == "depthX.png"
    assert find_node_by_title(wf, "brand:concept")[1]["inputs"]["image"] == "conceptX.png"
    # ControlNet consumes the depth; IPAdapter consumes the concept
    cnid = find_node_by_title(wf, "brand:depth")[0]
    ipid = find_node_by_title(wf, "brand:concept")[0]
    assert find_node_by_title(wf, "brand:cnapply")[1]["inputs"]["image"] == [cnid, 0]
    assert find_node_by_title(wf, "brand:ipadapter")[1]["inputs"]["image"] == [ipid, 0]


def test_sampler_takes_ipadapter_model_and_controlnet_conditioning():
    wf = _wf()
    ipid = find_node_by_title(wf, "brand:ipadapter")[0]
    cnid = find_node_by_title(wf, "brand:cnapply")[0]
    ks = find_node_by_title(wf, "brand:ksampler")[1]["inputs"]
    assert ks["model"] == [ipid, 0]          # IPAdapter-patched model
    assert ks["positive"] == [cnid, 0] and ks["negative"] == [cnid, 1]   # ControlNet-applied cond
    assert ks["seed"] == 7


def test_strengths_and_weight_are_tunable():
    wf = _wf(cn_strength=0.55, ip_weight=0.9)
    assert find_node_by_title(wf, "brand:cnapply")[1]["inputs"]["strength"] == 0.55
    assert find_node_by_title(wf, "brand:ipadapter")[1]["inputs"]["weight"] == 0.9


def test_generate_views_orchestration(tmp_path, monkeypatch):
    calls = {"uploads": [], "queued": 0}

    class FakeClient:
        def upload_image(self, p):
            calls["uploads"].append(Path(p).name); return "up_" + Path(p).name

        def queue_prompt(self, wf):
            calls["queued"] += 1; return f"pid{calls['queued']}"

        def wait(self, pid, max_wait=0):
            pass

    seen = {}

    def fake_runner(tmpl, params, **kw):
        seen["params"] = params
        assert "m.glb" in params["mesh"] and params["azimuths"] == [0.0, 180.0]
        return {"outputs": [str(tmp_path / "d0.png"), str(tmp_path / "d1.png")]}

    seq = iter([("v0.png", "", ""), ("v1.png", "", "")])
    monkeypatch.setattr(repaint, "select_output", lambda c, pid, wf: next(seq))
    views, depths = repaint.generate_views(
        FakeClient(), mesh=str(tmp_path / "m.glb"), concept_path=str(tmp_path / "c.png"),
        subject="a rover", azimuths=[0.0, 180.0], comfy_output_dir=str(tmp_path / "out"),
        out_dir=tmp_path, render_views_template="rv.py", blender_runner=fake_runner, seed=10,
        elevation=30.0)
    assert seen["params"]["elevation"] == 30.0   # elevation forwarded to the depth render
    assert len(views) == 2 and len(depths) == 2
    assert views[0].endswith("v0.png") and views[1].endswith("v1.png")
    assert calls["queued"] == 2                              # one repaint per depth view
    assert "c.png" in calls["uploads"]                       # concept uploaded for IPAdapter
    assert sum(1 for u in calls["uploads"] if u.startswith("d")) == 2   # both depths uploaded
