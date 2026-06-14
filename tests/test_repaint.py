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
