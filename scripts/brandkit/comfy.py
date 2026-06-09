"""Minimal ComfyUI HTTP client: queue a prompt, poll, list output files."""
from __future__ import annotations
import json, time, urllib.request
from pathlib import Path


class ComfyClient:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _upload(self, file_path, subfolder="", overwrite=True) -> str:
        """POST a local file into ComfyUI's input/ dir via /upload/image (stores any file
        type). Returns the name to reference in a Load* node (subfolder-prefixed if any)."""
        file_path = Path(file_path)
        boundary = "----brandkitFormBoundary7s8d9f"
        crlf = b"\r\n"

        def field(name, value):
            return (b"--" + boundary.encode() + crlf
                    + f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
                    + str(value).encode() + crlf)

        body = field("type", "input") + field("overwrite", "true" if overwrite else "false")
        if subfolder:
            body += field("subfolder", subfolder)
        body += (b"--" + boundary.encode() + crlf
                 + f'Content-Disposition: form-data; name="image"; filename="{file_path.name}"'.encode() + crlf
                 + b"Content-Type: application/octet-stream" + crlf + crlf
                 + file_path.read_bytes() + crlf
                 + b"--" + boundary.encode() + b"--" + crlf)
        req = urllib.request.Request(self.base + "/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            res = json.loads(r.read())
        name = res["name"]
        return f"{res['subfolder']}/{name}" if res.get("subfolder") else name

    def upload_image(self, file_path, subfolder="", overwrite=True) -> str:
        """Upload a local image into ComfyUI's input dir so LoadImage can resolve it."""
        return self._upload(file_path, subfolder=subfolder, overwrite=overwrite)

    def upload_video(self, file_path, subfolder="", overwrite=True) -> str:
        """Upload a local video into ComfyUI's input dir so LoadVideo can resolve it."""
        return self._upload(file_path, subfolder=subfolder, overwrite=overwrite)

    def queue_prompt(self, workflow: dict) -> str:
        body = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(self.base + "/prompt", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        if data.get("node_errors"):
            raise RuntimeError(f"ComfyUI validation errors: {data['node_errors']}")
        return data["prompt_id"]

    def free(self, unload_models: bool = True, free_memory: bool = True) -> None:
        """Ask ComfyUI to unload models / free VRAM (POST /free) before a heavy run, so
        sequential large models (e.g. a 22B video model then an image model) don't OOM."""
        body = json.dumps({"unload_models": unload_models, "free_memory": free_memory}).encode()
        req = urllib.request.Request(self.base + "/free", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout):
            pass

    def wait(self, prompt_id: str, poll=3, max_wait=900) -> dict:
        end = time.time() + max_wait
        while time.time() < end:
            hist = self._get(f"/history/{prompt_id}")
            rec = hist.get(prompt_id) if isinstance(hist, dict) else None
            if rec:
                status = rec.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI prompt {prompt_id} failed: "
                                       f"{status.get('messages', status)}")
                return hist
            time.sleep(poll)
        raise TimeoutError(f"prompt {prompt_id} did not finish in {max_wait}s")

    def output_files_by_node(self, prompt_id: str):
        """Every saved output file for a prompt, tagged with the node id that produced it:
        (node_id, filename, subfolder, type) tuples. Scans all list-valued output keys
        (images, gifs, videos, audio, …) so any extension is captured, not just images.
        Keeping the node id lets callers anchor on the canonical save node (by title) instead
        of trusting output-dict order — see outputs.select_output."""
        hist = self._get(f"/history/{prompt_id}")
        rec = hist.get(prompt_id, {})
        out = []
        for node_id, node in rec.get("outputs", {}).items():
            if not isinstance(node, dict):
                continue
            for val in node.values():
                if not isinstance(val, list):
                    continue
                for item in val:
                    if isinstance(item, dict) and "filename" in item:
                        out.append((node_id, item["filename"],
                                    item.get("subfolder", ""), item.get("type", "output")))
        return out

    def output_filenames(self, prompt_id: str):
        """Every saved output file for a prompt as (filename, subfolder, type) tuples (node id
        dropped). Format-agnostic — mp4 / webm / mov / gif / webp / wav are all captured, not
        just images. See output_files_by_node when the producing node matters."""
        return [t[1:] for t in self.output_files_by_node(prompt_id)]
