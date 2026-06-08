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
