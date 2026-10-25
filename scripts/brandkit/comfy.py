"""Minimal ComfyUI HTTP client: queue a prompt, poll, list output files."""
from __future__ import annotations
import json, time, urllib.error, urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"


class ComfyClient:
    def __init__(self, base_url=DEFAULT_URL, timeout=30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _upload(self, file_path, subfolder="", overwrite=False) -> str:
        """POST a local file into ComfyUI's input/ dir via /upload/image (stores any file
        type). Returns the name to reference in a Load* node (subfolder-prefixed if any).

        overwrite stays off: LoadImage reads its file when the job runs, so with it on a second run (another
        terminal, an agent firing several jobs) replaced the first run's same-named input (logos/primary.png,
        product.png) before that job read it (2026-10-25 review). Off, ComfyUI keeps a file whose content is
        identical and stores different content under a free name ("primary (1).png"); its reply names the
        file either way, which is what this returns and every caller puts in the graph."""
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

    def upload_image(self, file_path, subfolder="", overwrite=False) -> str:
        """Upload a local image into ComfyUI's input dir so LoadImage can resolve it."""
        return self._upload(file_path, subfolder=subfolder, overwrite=overwrite)

    def upload_video(self, file_path, subfolder="", overwrite=False) -> str:
        """Upload a local video into ComfyUI's input dir so LoadVideo can resolve it."""
        return self._upload(file_path, subfolder=subfolder, overwrite=overwrite)

    def queue_prompt(self, workflow: dict) -> str:
        body = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(self.base + "/prompt", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # ComfyUI answers validation failures with HTTP 400 and the per-node detail in the
            # BODY — read it so callers see WHICH node/input was rejected, not a bare 400.
            try:
                detail = json.loads(e.read())
            except Exception:
                raise RuntimeError(f"ComfyUI rejected the prompt (HTTP {e.code})") from e
            raise RuntimeError("ComfyUI validation errors: "
                               f"{detail.get('node_errors') or detail.get('error') or detail}") from e
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

    def system_stats(self) -> dict:
        """GET /system_stats — ComfyUI engine + device info. Raises on an unreachable server."""
        return self._get("/system_stats")

    def object_info(self) -> dict:
        """GET /object_info — every installed node class_type and its schema (including available
        model filenames as dropdown enums). Used by the `doctor` preflight. Raises if unreachable."""
        return self._get("/object_info")

    def comfyui_version(self):
        """Best-effort ComfyUI version string from /system_stats, for the reproducibility sidecar.
        None if the server doesn't report it or is unreachable — never raises (provenance is
        optional and must not fail a completed render)."""
        try:
            data = self.system_stats()
            info = data.get("system", {}) if isinstance(data, dict) else {}
            return info.get("comfyui_version") or None
        except Exception:
            return None

    def _queued(self, prompt_id):
        """Whether /queue lists the prompt as running or pending; None when /queue can't be read."""
        try:
            q = self._get("/queue")
        except (OSError, ValueError):
            return None
        if not isinstance(q, dict) or not ({"queue_running", "queue_pending"} & q.keys()):
            return None   # not ComfyUI's /queue (a proxy's page, an odd server): no evidence either way
        items = [*(q.get("queue_running") or []), *(q.get("queue_pending") or [])]
        # each item is [number, prompt_id, prompt, extra_data, outputs_to_execute]
        return any(isinstance(i, list) and len(i) > 1 and i[1] == prompt_id for i in items)

    @staticmethod
    def _finished(hist, prompt_id):
        """The history dict once the prompt has a record (raising if it failed), else None."""
        rec = hist.get(prompt_id) if isinstance(hist, dict) else None
        if not rec:
            return None
        status = rec.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI prompt {prompt_id} failed: {status.get('messages', status)}")
        return hist

    def wait(self, prompt_id: str, poll=3, max_wait=900, max_misses=20, queue_every=5) -> dict:
        end, misses, empty = time.time() + max_wait, 0, 0
        while time.time() < end:
            try:
                hist = self._get(f"/history/{prompt_id}")
            except OSError as e:   # URLError, a reset socket, a 5xx while ComfyUI is busy
                # a brief drop must not abort a long render whose output is still there to route; give up
                # only after ~max_misses polls in a row fail
                misses += 1
                if misses >= max_misses:
                    raise ConnectionError(f"lost contact with ComfyUI at {self.base} while waiting for "
                                          f"{prompt_id} ({e})") from e
                time.sleep(poll)
                continue
            misses = 0
            done = self._finished(hist, prompt_id)
            if done:
                return done
            # A prompt that ComfyUI dropped (it restarted mid-render, or the job was cancelled from its queue)
            # never gets a history record, and this waited it out as running for up to an hour (2026-10-25).
            # Every few empty polls, ask /queue; a prompt in neither list has gone, unless it finished between
            # the two reads, so history gets one more look first.
            empty += 1
            if empty % queue_every == 0 and self._queued(prompt_id) is False:
                try:
                    done = self._finished(self._get(f"/history/{prompt_id}"), prompt_id)
                except OSError:
                    done = None
                if done:
                    return done
                raise RuntimeError(f"ComfyUI prompt {prompt_id} is no longer queued and left no result: ComfyUI "
                                   "restarted, or the job was cancelled from its queue")
            time.sleep(poll)
        raise TimeoutError(f"prompt {prompt_id} did not finish in {max_wait}s")

    def output_files_by_node(self, prompt_id: str, history=None):
        """Every saved output file for a prompt, tagged with the node id that produced it:
        (node_id, filename, subfolder, type) tuples. Scans all list-valued output keys
        (images, gifs, videos, audio, …) so any extension is captured, not just images.
        Keeping the node id lets callers anchor on the canonical save node (by title) instead
        of trusting output-dict order — see outputs.select_output. Pass the dict wait()
        returned as `history` to skip a redundant /history re-fetch."""
        hist = history if history is not None else self._get(f"/history/{prompt_id}")
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

    def output_filenames(self, prompt_id: str, history=None):
        """Every saved output file for a prompt as (filename, subfolder, type) tuples (node id
        dropped). Format-agnostic — mp4 / webm / mov / gif / webp / wav are all captured, not
        just images. See output_files_by_node when the producing node matters."""
        return [t[1:] for t in self.output_files_by_node(prompt_id, history=history)]
