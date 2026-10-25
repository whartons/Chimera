import pytest
import scripts.brandkit.outputs as outputs
from scripts.brandkit.outputs import brand_output_dir, route_output

def test_brand_output_dir(tmp_path):
    d = brand_output_dir(tmp_path, "example-brand")
    assert d == tmp_path / "brands" / "example-brand" / "outputs"

def test_route_moves_file(tmp_path):
    src = tmp_path / "global" / "img_00001_.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"PNG")
    dest = route_output(repo_root=tmp_path, brand="example-brand", src=src,
                        mode="txt2img", seed=7)
    assert dest.exists() and not src.exists()
    # routed by media type: a .png lands under outputs/images/
    assert dest.parent == tmp_path / "brands" / "example-brand" / "outputs" / "images"
    assert dest.name == "example-brand_txt2img_7.png"

def test_route_by_media_type(tmp_path):
    # foley is a video file -> video/ ; music is audio -> audio/ ; 3d -> 3d/
    for ext, sub in ((".mp4", "video"), (".mp3", "audio"), (".glb", "3d")):
        src = tmp_path / "global" / f"x{ext}"
        src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(b"X")
        dest = route_output(tmp_path, "example-brand", src, "foley", 42)
        assert dest.parent == tmp_path / "brands" / "example-brand" / "outputs" / sub
        assert dest.name == f"example-brand_foley_42{ext}"

def test_route_brandless_goes_to_global_outputs(tmp_path):
    # brandless (brand=None): route to the global outputs/<media>/<mode>_<seed>, moved (not in place)
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    dest = route_output(repo_root=tmp_path, brand=None, src=src, mode="txt2img", seed=1)
    assert dest.exists() and not src.exists()
    assert dest == tmp_path / "outputs" / "images" / "txt2img_1.png"

def _meta(prompt="a red cat", values="v1", hashes=None):
    """A render sidecar's identity-bearing fields (sidecar.build_meta's shape)."""
    prov = {"graph_signature": "sig", "graph_values": values}
    if hashes:
        prov["input_hashes"] = hashes
    return {"schema": 2, "modality": "image", "mode": "txt2img", "seed": 7, "prompt": prompt, "negative": "",
            "provenance": prov}


def _rendered(out_dir, stem, meta, data=b"OLD"):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.png").write_bytes(data)
    (out_dir / f"{stem}.json").write_text(_json.dumps(meta), encoding="utf-8")


def _src(tmp_path, data=b"NEW"):
    src = tmp_path / "global" / "new.png"
    src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(data)
    return src


def test_route_overwrites_existing_dest(tmp_path):
    # an identical re-render (same graph, same prompts, same input files) replaces the earlier one cleanly
    from scripts.brandkit.sidecar import render_identity
    out_dir = tmp_path / "brands" / "example-brand" / "outputs" / "images"
    _rendered(out_dir, "example-brand_txt2img_7", _meta(hashes={"asset": "abc"}))
    src = _src(tmp_path)
    dest = route_output(repo_root=tmp_path, brand="example-brand", src=src, mode="txt2img", seed=7,
                        identity=render_identity(_meta(hashes={"asset": "abc"})))
    assert dest.name == "example-brand_txt2img_7.png"
    assert dest.read_bytes() == b"NEW" and not src.exists()
    assert sorted(p.name for p in out_dir.iterdir()) == ["example-brand_txt2img_7.json", "example-brand_txt2img_7.png"]


@pytest.mark.parametrize("new", [_meta(prompt="a blue dog"), _meta(values="v2"),
                                 _meta(hashes={"asset": "other"})], ids=["prompt", "settings", "input-file"])
def test_a_different_render_with_the_same_seed_keeps_both(tmp_path, new):
    # 'a red cat' then 'a blue dog' with --seed 7 left only the dog: route_output replaced the cat and its sidecar
    from scripts.brandkit.sidecar import render_identity
    out_dir = tmp_path / "brands" / "b" / "outputs" / "images"
    _rendered(out_dir, "b_txt2img_7", _meta(hashes={"asset": "abc"} if "input_hashes" in new["provenance"] else None))
    dest = route_output(tmp_path, "b", _src(tmp_path), "txt2img", 7, identity=render_identity(new))
    assert dest.name == "b_txt2img_7_2.png" and dest.read_bytes() == b"NEW"
    assert (out_dir / "b_txt2img_7.png").read_bytes() == b"OLD"


def test_the_next_free_name_counts_up_and_an_identical_render_reuses_its_own(tmp_path):
    from scripts.brandkit.sidecar import render_identity
    out_dir = tmp_path / "brands" / "b" / "outputs" / "images"
    _rendered(out_dir, "b_txt2img_7", _meta("a red cat"))
    _rendered(out_dir, "b_txt2img_7_2", _meta("a blue dog"))
    third = route_output(tmp_path, "b", _src(tmp_path, b"FROG"), "txt2img", 7, identity=render_identity(_meta("frog")))
    assert third.name == "b_txt2img_7_3.png"
    again = route_output(tmp_path, "b", _src(tmp_path, b"DOG2"), "txt2img", 7,
                         identity=render_identity(_meta("a blue dog")))
    assert again.name == "b_txt2img_7_2.png" and again.read_bytes() == b"DOG2"   # the dog's own name, replaced


def test_a_caller_that_cannot_tell_never_replaces(tmp_path):
    # no identity (a Blender job, an agent iteration) or no readable sidecar: the earlier file is kept
    from scripts.brandkit.sidecar import render_identity
    out_dir = tmp_path / "outputs" / "images"
    _rendered(out_dir, "txt2img_7", _meta())
    assert route_output(tmp_path, None, _src(tmp_path), "txt2img", 7).name == "txt2img_7_2.png"
    (out_dir / "txt2img_7.json").write_text("{not json", encoding="utf-8")
    assert route_output(tmp_path, None, _src(tmp_path), "txt2img", 7, identity=render_identity(_meta())).name == \
        "txt2img_7_3.png"


def test_an_old_sidecar_without_a_graph_record_is_never_the_same_render():
    from scripts.brandkit.sidecar import render_identity
    assert render_identity({"schema": 1, "prompt": "x"}) is None
    assert render_identity({"schema": 2, "kind": "cad", "provenance": {"params_signature": "p"}}) is None
    assert render_identity(_meta()) == render_identity(_json.loads(_json.dumps(_meta())))   # survives the file


def test_a_jobs_files_share_one_free_name_across_their_folders(tmp_path):
    # Blender/FreeCAD jobs route several files under one name (STEP+STL, PNG+GLB): a per-file free name split
    # them (STL _2, GLB _3), so the job picks one name free in every folder it writes to
    (tmp_path / "outputs" / "images").mkdir(parents=True)
    (tmp_path / "outputs" / "images" / "finish_7.png").write_bytes(b"old still")
    srcs = [tmp_path / "a.stl", tmp_path / "a.glb"]
    assert outputs.job_stem(tmp_path, None, srcs, "finish", 7) == "finish_7"      # 3d/ is empty: first free
    srcs.append(tmp_path / "a.png")
    stem = outputs.job_stem(tmp_path, None, srcs, "finish", 7)
    assert stem == "finish_7_2"                                                    # images/ holds finish_7
    for s in srcs:
        s.write_bytes(b"new")
    routed = [route_output(tmp_path, None, s, "finish", 7, stem=stem).name for s in srcs]
    assert routed == ["finish_7_2.stl", "finish_7_2.glb", "finish_7_2.png"]
    with pytest.raises(NoOutputError, match="plain names"):
        outputs.job_stem(tmp_path, None, srcs, "../x", 7)
    other = tmp_path / "b.png"
    other.write_bytes(b"x")
    for bad in (dict(brand="..", stem="ok"), dict(brand=None, stem="../escape")):   # a picked name is checked too
        with pytest.raises(NoOutputError):
            route_output(tmp_path, bad["brand"], other, "finish", 7, stem=bad["stem"])
    assert other.exists()

def test_route_retries_on_transient_lock(tmp_path, monkeypatch):
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    real_move, calls = outputs.shutil.move, {"n": 0}
    def flaky_move(s, d):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("file locked by sync client")
        return real_move(s, d)
    monkeypatch.setattr(outputs.shutil, "move", flaky_move)
    dest = route_output(tmp_path, "example-brand", src, "txt2img", 9, _delay=0)
    assert dest.exists() and not src.exists() and calls["n"] == 2

def test_route_reraises_after_persistent_lock(tmp_path, monkeypatch):
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    def always_locked(s, d):
        raise PermissionError("still locked")
    monkeypatch.setattr(outputs.shutil, "move", always_locked)
    with pytest.raises(PermissionError):
        route_output(tmp_path, "example-brand", src, "txt2img", 9, _retries=3, _delay=0)

import json as _json
from scripts.brandkit.outputs import first_output, select_output, NoOutputError, write_sidecar

def test_first_output_returns_first_tuple():
    files = [("a.png", "", "output"), ("b.png", "sub", "output")]
    assert first_output(files) == ("a.png", "", "output")

def test_first_output_empty_raises_with_seed_hint():
    with pytest.raises(NoOutputError) as e:
        first_output([])
    assert "seed" in str(e.value).lower()

def test_first_output_prefers_node_id():
    # 4-tuples (node_id, filename, subfolder, type); the preferred node's file wins over order
    files = [("9", "preview.png", "", "output"), ("10", "final.png", "b", "output")]
    assert first_output(files, prefer_node_id="10") == ("final.png", "b", "output")

def test_first_output_prefer_node_id_falls_back_to_first():
    # preferred node produced no file -> degrade to the first (node id stripped)
    files = [("9", "preview.png", "", "output")]
    assert first_output(files, prefer_node_id="10") == ("preview.png", "", "output")


class _FakeClient:
    def __init__(self, by_node):
        self._by_node = by_node
    def output_files_by_node(self, pid):
        return self._by_node
    def output_filenames(self, pid):
        return [t[1:] for t in self._by_node]

def test_select_output_anchors_on_brand_save():
    # a graph with a preview saver AND the canonical brand:save: select the brand:save file,
    # not the positionally-first preview
    wf = {"9": {"_meta": {"title": "brand:preview"}, "inputs": {}},
          "10": {"_meta": {"title": "brand:save"}, "inputs": {}}}
    client = _FakeClient([("9", "preview.png", "", "output"), ("10", "final.png", "b", "output")])
    assert select_output(client, "p", wf) == ("final.png", "b", "output")

def test_select_output_degrades_without_brand_save():
    # no brand:save title -> legacy first-file behavior via output_filenames
    wf = {"9": {"_meta": {"title": "brand:other"}, "inputs": {}}}
    client = _FakeClient([("9", "a.png", "", "output")])
    assert select_output(client, "p", wf) == ("a.png", "", "output")

def test_select_output_empty_raises():
    client = _FakeClient([])
    with pytest.raises(NoOutputError):
        select_output(client, "p", {"1": {"_meta": {"title": "brand:save"}}})

def test_write_sidecar_records_model_and_seed(tmp_path):
    out = tmp_path / "brand_txt2img_7.png"; out.write_bytes(b"PNG")
    meta = {"seed": 7, "model": "z_image_bf16.safetensors", "mode": "txt2img",
            "prompt": "p", "negative": "n", "comfy_url": "http://x", "template": "brand-txt2img.json"}
    side = write_sidecar(out, meta)
    assert side == out.with_suffix(".json") and side.exists()
    data = _json.loads(side.read_text())
    assert data["model"] == "z_image_bf16.safetensors" and data["seed"] == 7


def test_run_graph_to_file_queues_waits_selects_and_reuses_history(tmp_path):
    # the queue -> wait -> select -> local-path dance every generator hand-rolled; must anchor
    # on brand:save and reuse wait()'s history record (no /history re-fetch)
    from pathlib import Path as _P
    from scripts.brandkit.outputs import run_graph_to_file
    wf = {"9": {"class_type": "SaveImage", "_meta": {"title": "brand:save"}, "inputs": {}}}
    class C:
        def queue_prompt(self, w):
            return "pid1"
        def wait(self, pid, max_wait=None):
            assert max_wait == 123
            return {"pid1": {"outputs": {"9": {"images": [{"filename": "a.png",
                                                           "subfolder": "sub"}]}}}}
        def output_files_by_node(self, pid, history=None):
            assert history is not None, "must reuse wait()'s history"
            rec = history[pid]
            return [(nid, i["filename"], i.get("subfolder", ""), "output")
                    for nid, n in rec["outputs"].items() for i in n["images"]]
    p = run_graph_to_file(C(), wf, tmp_path, timeout=123)
    assert p == _P(tmp_path) / "sub" / "a.png"


# --- a replay never replaces the render it reproduces (2026-10 review, P1) ---------------------------
def test_route_keep_existing_takes_the_next_free_name(tmp_path):
    out = tmp_path / "brands" / "b" / "outputs" / "images"; out.mkdir(parents=True)
    (out / "b_txt2img_7.png").write_bytes(b"ORIGINAL"); (out / "b_txt2img_7.json").write_text("{}")
    names = []
    for i in range(3):
        src = tmp_path / f"r{i}.png"; src.write_bytes(b"REPLAY")
        names.append(route_output(tmp_path, "b", src, "txt2img", 7, keep_existing=True).name)
    assert names == ["b_txt2img_7_replay.png", "b_txt2img_7_replay2.png", "b_txt2img_7_replay3.png"]
    assert (out / "b_txt2img_7.png").read_bytes() == b"ORIGINAL"


def test_route_keep_existing_counts_a_sidecar_without_its_render(tmp_path):
    # a 3D render converted to STL leaves no GLB under its stem, only the .stl + sidecar
    out = tmp_path / "outputs" / "3d"; out.mkdir(parents=True)
    (out / "image_5.stl").write_text("solid"); (out / "image_5.json").write_text("{}")
    src = tmp_path / "m.glb"; src.write_bytes(b"glb")
    assert route_output(tmp_path, None, src, "image", 5, keep_existing=True).name == "image_5_replay.glb"


def test_route_keep_existing_uses_the_plain_name_when_free(tmp_path):
    src = tmp_path / "a.png"; src.write_bytes(b"x")
    assert route_output(tmp_path, "b", src, "txt2img", 9, keep_existing=True).name == "b_txt2img_9.png"


@pytest.mark.parametrize("sub, name", [("", "C:/Users/x/notes.docx"), ("", "/etc/passwd"),
                                        ("../..", "x.png"), ("a/../../b", "x.png"), ("C:/", "x.png")])
def test_comfy_output_path_refuses_names_outside_the_output_dir(tmp_path, sub, name):
    # the names come from ComfyUI's /history: a hostile server could point the CLI at any local file
    with pytest.raises(NoOutputError, match="outside"):
        outputs.comfy_output_path(tmp_path, sub, name)


def test_comfy_output_path_keeps_a_normal_subfolder(tmp_path):
    assert outputs.comfy_output_path(tmp_path, "video", "clip_00001_.mp4") == tmp_path / "video" / "clip_00001_.mp4"
    assert outputs.comfy_output_path(tmp_path, "", "img.png") == tmp_path / "img.png"



# --- a repeated identical job still writes a new file (2026-10) ------------------------------------------
def test_fresh_output_name_makes_each_queued_save_unique():
    def wf():
        return {"9": {"class_type": "SaveImage", "_meta": {"title": "brand:save"},
                      "inputs": {"filename_prefix": "brand_txt2img", "images": ["8", 0]}}}
    a, b = outputs.fresh_output_name(wf()), outputs.fresh_output_name(wf())
    pa, pb = a["9"]["inputs"]["filename_prefix"], b["9"]["inputs"]["filename_prefix"]
    assert pa.startswith("brand_txt2img_") and pb.startswith("brand_txt2img_") and pa != pb
    assert outputs.fresh_output_name({"1": {"class_type": "X", "inputs": {}}}) == {"1": {"class_type": "X", "inputs": {}}}


def test_run_graph_to_file_queues_a_fresh_output_name(tmp_path):
    seen = {}

    class C:
        def queue_prompt(self, w):
            seen["prefix"] = w["9"]["inputs"]["filename_prefix"]
            return "pid"

        def wait(self, pid, max_wait=None):
            return {"pid": {"outputs": {"9": {"images": [{"filename": "a.png", "subfolder": ""}]}}}}

        def output_files_by_node(self, pid, history=None):
            return [("9", "a.png", "", "output")]
    wf = {"9": {"class_type": "SaveImage", "_meta": {"title": "brand:save"}, "inputs": {"filename_prefix": "agent"}}}
    outputs.run_graph_to_file(C(), wf, tmp_path)
    assert seen["prefix"].startswith("agent_") and seen["prefix"] != "agent"


def test_route_output_says_clearly_when_the_reported_file_is_missing(tmp_path):
    with pytest.raises(NoOutputError, match="isn't in its output folder"):
        route_output(tmp_path, "b", tmp_path / "gone.png", "txt2img", 1)



# --- names that arrive from outside stay one plain name (2026-10 review) ---------------------------------
@pytest.mark.parametrize("name, ok", [("rover.png", True), ("my brand", True), ("Café & Co", True), ("", False),
                                      (".", False), ("..", False), ("a/b", False), ("a\\b", False), ("c:x", False),
                                      ("x.", False), (" x", False), ("a\tb", False)])
def test_plain_name(name, ok):
    assert outputs.plain_name(name) is ok


def test_route_output_refuses_a_mode_or_brand_that_is_a_path(tmp_path):
    from scripts.brandkit.outputs import NoOutputError
    src = tmp_path / "r.png"
    src.write_bytes(b"x")
    with pytest.raises(NoOutputError, match="plain names"):
        route_output(tmp_path, None, src, "../../evil", 42)
    with pytest.raises(NoOutputError, match="plain names"):
        route_output(tmp_path, "..", src, "txt2img", 42)
    with pytest.raises(NoOutputError):
        route_output(tmp_path, "b", tmp_path, "txt2img", 1)      # a folder isn't an output file
    assert src.exists()


def test_comfy_output_path_refuses_an_empty_or_dot_name(tmp_path):
    # '.' passed the check and moved ComfyUI's whole output folder into the brand's outputs
    from scripts.brandkit.outputs import NoOutputError, comfy_output_path
    for bad in ("", ".", ".."):
        with pytest.raises(NoOutputError):
            comfy_output_path(tmp_path, "", bad)


def test_a_replay_name_ignores_case_like_windows_does(tmp_path):
    (tmp_path / "Example_txt2img_9.png").write_bytes(b"orig")
    assert outputs._unused_stem(tmp_path, "example_txt2img_9") == "example_txt2img_9_replay"



# --- 2026-10 test review --------------------------------------------------------------------------------
def test_plain_name_refuses_an_ntfs_stream_name():
    assert not outputs.plain_name("rover.png:hidden")


def test_a_longer_seed_does_not_count_as_taken(tmp_path):
    (tmp_path / "b_txt2img_70.png").write_bytes(b"x")
    assert outputs._unused_stem(tmp_path, "b_txt2img_7") == "b_txt2img_7"


def test_run_graph_to_file_refuses_a_history_name_outside_the_output_dir(tmp_path):
    class C:
        def queue_prompt(self, w): return "pid"
        def wait(self, pid, max_wait=None): return {"pid": {}}
        def output_files_by_node(self, pid, history=None): return [("9", "notes.docx", "../..", "output")]
    wf = {"9": {"class_type": "SaveImage", "_meta": {"title": "brand:save"}, "inputs": {"filename_prefix": "a"}}}
    with pytest.raises(outputs.NoOutputError, match="outside"):
        outputs.run_graph_to_file(C(), wf, tmp_path)


def test_route_output_names_the_app_that_listed_a_missing_file(tmp_path):
    # a Blender or FreeCAD job used to be reported as ComfyUI's, with a --comfy-output-dir hint
    with pytest.raises(outputs.NoOutputError, match="Blender listed ghost.png as an output"):
        route_output(tmp_path, "b", tmp_path / "ghost.png", "mesh", 1, producer="Blender")


# --- 2026-10-25 review -------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ['my"brand', "a<b", "a>b", "a|b", "what?", "star*", "a:b", "a/b", "a\\b",
                                  "bell\x07", "del\x7f", "c1\x85"])
def test_a_brand_name_windows_cannot_create_is_refused(name):
    # `new-brand 'what?'` passed the check, then copytree raised WinError 123; a '"' broke brand.yaml's name:
    assert outputs.brand_name_ok(name) is False


@pytest.mark.parametrize("name", ["acme", "my brand", "Café & Co", "東京-brand", "it's #1", "a.b"])
def test_an_ordinary_brand_name_is_still_accepted(name):
    assert outputs.brand_name_ok(name) is True
