import json, io
import pytest
from scripts.brandkit import comfy

class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_queue_prompt_posts_and_returns_id(monkeypatch):
    captured = {}
    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(json.dumps({"prompt_id": "abc"}).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    pid = c.queue_prompt({"1": {"class_type": "X", "inputs": {}}})
    assert pid == "abc"
    assert captured["url"].endswith("/prompt")
    assert "prompt" in captured["body"]

def test_queue_prompt_surfaces_validation_detail_on_http_400(monkeypatch):
    # ComfyUI answers validation failures with HTTP 400 + per-node detail in the BODY; the
    # client must surface that detail, not a bare urllib HTTPError
    import urllib.error
    body = json.dumps({"error": {"type": "prompt_outputs_failed_validation"},
                       "node_errors": {"5": {"errors": [{"message": "value not in list"}]}}}).encode()
    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError("http://x/prompt", 400, "Bad Request", {}, io.BytesIO(body))
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="value not in list"):
        comfy.ComfyClient("http://x").queue_prompt({"1": {}})


def test_output_files_by_node_reuses_passed_history(monkeypatch):
    # wait() already returned the full history record — a caller passing it must not trigger
    # a second /history fetch
    hist = {"pid": {"outputs": {"9": {"images": [{"filename": "a.png"}]}}}}
    def no_net(req, timeout=0):
        raise AssertionError("must not re-fetch /history when history is passed")
    monkeypatch.setattr(comfy.urllib.request, "urlopen", no_net)
    out = comfy.ComfyClient("http://x").output_files_by_node("pid", history=hist)
    assert out == [("9", "a.png", "", "output")]


def test_upload_image_posts_multipart_and_returns_name(monkeypatch, tmp_path):
    img = tmp_path / "primary.png"; img.write_bytes(b"\x89PNG\r\n\x1a\nDATA")
    captured = {}
    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["ctype"] = req.headers.get("Content-type")
        captured["data"] = req.data
        return FakeResp(json.dumps({"name": "primary.png", "subfolder": "", "type": "input"}).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    name = c.upload_image(img)
    assert name == "primary.png"
    assert captured["url"].endswith("/upload/image")
    assert captured["ctype"].startswith("multipart/form-data; boundary=")
    assert b'filename="primary.png"' in captured["data"]
    assert b"DATA" in captured["data"]  # the file bytes are in the body

def test_upload_image_prefixes_subfolder(monkeypatch, tmp_path):
    img = tmp_path / "p.png"; img.write_bytes(b"X")
    def fake_urlopen(req, timeout=0):
        return FakeResp(json.dumps({"name": "p.png", "subfolder": "brand", "type": "input"}).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    assert c.upload_image(img) == "brand/p.png"

def test_history_output_filenames(monkeypatch):
    hist = {"abc": {"status": {"status_str": "success"},
                    "outputs": {"10": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}}
    def fake_urlopen(req, timeout=0):
        return FakeResp(json.dumps(hist).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    files = c.output_filenames("abc")
    assert files == [("f.png", "", "output")]

def test_output_filenames_includes_subfolder(monkeypatch):
    hist = {"abc": {"outputs": {"10": {"images": [
        {"filename": "f.png", "subfolder": "brand", "type": "output"}]}}}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(hist).encode()))
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    assert c.output_filenames("abc") == [("f.png", "brand", "output")]

def test_output_filenames_across_node_keys(monkeypatch):
    # video save nodes report under varied keys (gifs/videos), not just images;
    # any extension (webm/mp4/mov/gif) must be captured by its filename.
    hist = {"p": {"outputs": {
        "9":  {"gifs":   [{"filename": "a.webm", "subfolder": "video", "type": "output"}]},
        "10": {"images": [{"filename": "b.mp4",  "subfolder": "video", "type": "output"}]},
        "11": {"text":   ["not-a-file"]},  # non-file lists are ignored
    }}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(hist).encode()))
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    got = set(c.output_filenames("p"))
    assert ("a.webm", "video", "output") in got
    assert ("b.mp4", "video", "output") in got
    assert len(got) == 2

def test_output_files_by_node_keeps_node_id(monkeypatch):
    # the node-id-tagged variant lets callers anchor on the canonical save node by title
    hist = {"p": {"outputs": {
        "9":  {"images": [{"filename": "preview.png", "subfolder": "", "type": "output"}]},
        "10": {"images": [{"filename": "final.png", "subfolder": "b", "type": "output"}]},
    }}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(hist).encode()))
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    got = set(c.output_files_by_node("p"))
    assert ("9", "preview.png", "", "output") in got
    assert ("10", "final.png", "b", "output") in got
    # and output_filenames is the same data with the node id dropped (kept backward-compatible)
    assert set(c.output_filenames("p")) == {(f, s, t) for _, f, s, t in got}


def test_wait_returns_on_success(monkeypatch):
    hist = {"abc": {"status": {"status_str": "success"}, "outputs": {}}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(hist).encode()))
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    assert c.wait("abc") == hist

def test_wait_raises_on_error(monkeypatch):
    hist = {"abc": {"status": {"status_str": "error", "messages": [["execution_error", {"x": 1}]]}}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(hist).encode()))
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    with pytest.raises(RuntimeError):
        c.wait("abc")

def test_system_stats_returns_parsed_dict(monkeypatch):
    payload = {"system": {"comfyui_version": "v9"}, "devices": []}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(payload).encode()))
    assert comfy.ComfyClient().system_stats() == payload

def test_object_info_returns_parsed_dict(monkeypatch):
    payload = {"KSampler": {"input": {"required": {}}}, "UNETLoader": {"input": {"required": {}}}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(payload).encode()))
    assert comfy.ComfyClient().object_info() == payload

def test_comfyui_version_from_system_stats(monkeypatch):
    payload = {"system": {"comfyui_version": "v0.24.1", "python_version": "3.12.11"}}
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps(payload).encode()))
    assert comfy.ComfyClient().comfyui_version() == "v0.24.1"

def test_comfyui_version_missing_field_returns_none(monkeypatch):
    monkeypatch.setattr(comfy.urllib.request, "urlopen",
                        lambda req, timeout=0: FakeResp(json.dumps({"system": {}}).encode()))
    assert comfy.ComfyClient().comfyui_version() is None

def test_comfyui_version_unreachable_returns_none(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("connection refused")
    monkeypatch.setattr(comfy.urllib.request, "urlopen", boom)
    assert comfy.ComfyClient().comfyui_version() is None  # provenance is optional, must not raise

def test_free_posts_unload_and_free_flags(monkeypatch):
    captured = {}
    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(b"")
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    c = comfy.ComfyClient("http://127.0.0.1:8000")
    c.free(unload_models=True, free_memory=True)
    assert captured["url"].endswith("/free")
    assert captured["body"] == {"unload_models": True, "free_memory": True}

def test_upload_video_posts_to_upload_image_and_returns_name(monkeypatch, tmp_path):
    captured = {}
    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return FakeResp(json.dumps({"name": "clip.mp4", "subfolder": "", "type": "input"}).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake_urlopen)
    v = tmp_path / "clip.mp4"; v.write_bytes(b"\x00\x01fakevideo")
    name = comfy.ComfyClient().upload_video(v)
    assert name == "clip.mp4"
    assert captured["url"].endswith("/upload/image")
    assert b'filename="clip.mp4"' in captured["body"]


def test_wait_rides_out_a_brief_connection_drop(monkeypatch):
    # a dropped poll used to abort a long render (raw URLError) even though its output was saved
    hist = {"abc": {"status": {"status_str": "success"}, "outputs": {}}}
    calls = []

    def flaky(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise comfy.urllib.error.URLError("connection reset")
        return FakeResp(json.dumps(hist).encode())

    monkeypatch.setattr(comfy.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(comfy.time, "sleep", lambda s: None)
    assert comfy.ComfyClient().wait("abc") == hist and len(calls) == 3


def test_wait_gives_up_with_a_clear_error_when_comfyui_stays_down(monkeypatch):
    def down(req, timeout=0):
        raise comfy.urllib.error.URLError("refused")
    monkeypatch.setattr(comfy.urllib.request, "urlopen", down)
    monkeypatch.setattr(comfy.time, "sleep", lambda s: None)
    with pytest.raises(ConnectionError, match="lost contact with ComfyUI"):
        comfy.ComfyClient().wait("abc", max_misses=3)


# --- a prompt that vanished from ComfyUI fails instead of waiting out the timeout (2026-10-25 review) --------
class _Clock:
    """comfy.time stand-in: sleep() advances the clock, so a wait that never ends hits max_wait at once."""
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


def _route(monkeypatch, history, queue):
    """A urlopen fake answering /history/<id> and /queue from callables (one call per request)."""
    calls = []

    def fake(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        calls.append(url)
        return FakeResp(json.dumps(queue() if url.endswith("/queue") else history()).encode())
    monkeypatch.setattr(comfy.urllib.request, "urlopen", fake)
    monkeypatch.setattr(comfy, "time", _Clock())
    return calls


_DONE = {"abc": {"status": {"status_str": "success"}, "outputs": {}}}
_EMPTY_QUEUE = {"queue_running": [], "queue_pending": []}


def _history_after(n):
    """/history/abc answers {} for the first n polls, then the finished record."""
    polls = {"n": 0}

    def history():
        polls["n"] += 1
        return _DONE if polls["n"] > n else {}
    return history


def test_wait_fails_when_the_prompt_is_neither_queued_nor_in_history(monkeypatch):
    # ComfyUI restarted mid-render, or the job was cancelled from its queue: /history/<id> stays {} forever
    calls = _route(monkeypatch, lambda: {}, lambda: _EMPTY_QUEUE)
    with pytest.raises(RuntimeError, match="no longer queued"):
        comfy.ComfyClient().wait("abc", max_wait=3600)
    assert len(calls) < 20   # found out within a few polls, not after an hour


def test_wait_keeps_waiting_while_the_prompt_is_still_queued(monkeypatch):
    _route(monkeypatch, _history_after(30), lambda: {"queue_running": [[0, "other", {}, {}, []]],
                                                     "queue_pending": [[1, "abc", {}, {}, []]]})
    assert comfy.ComfyClient().wait("abc") == _DONE


def test_wait_rereads_history_once_when_the_job_finished_between_the_two_reads(monkeypatch):
    # /history said "not yet", then the job finished before /queue was read: the result is there on a re-read
    _route(monkeypatch, _history_after(5), lambda: _EMPTY_QUEUE)
    assert comfy.ComfyClient().wait("abc") == _DONE


def _queue_down():
    raise comfy.urllib.error.URLError("reset")


@pytest.mark.parametrize("queue", [_queue_down, lambda: {}], ids=["read-fails", "not-comfyuis-queue"])
def test_wait_rides_out_a_queue_read_that_tells_nothing(monkeypatch, queue):
    # the /queue check is a hint: a failed or unrecognised read must not abort a render that is still running
    _route(monkeypatch, _history_after(12), queue)
    assert comfy.ComfyClient().wait("abc") == _DONE
