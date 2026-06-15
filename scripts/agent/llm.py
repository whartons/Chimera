"""Provider-agnostic LLM backend for the agent loop — autonomous AI judge (#2) and CAD code-gen (#1).

Targets the **OpenAI-compatible `/v1/chat/completions`** shape, the de-facto lingua franca, so ONE
implementation works with **Google Gemini**, OpenAI, **Anthropic's OpenAI-compat endpoint**, OpenRouter,
Together, Groq, or a **local** server (Ollama / LM Studio / vLLM / llama.cpp). No vendor SDK — pure stdlib
urllib/json/base64 (zero new deps, CI-safe). Vision uses the OpenAI `image_url` data-URI part.

Config (env, with CLI overrides; no hardcoded vendor default):
  CHIMERA_LLM_BASE_URL  https://generativelanguage.googleapis.com/v1beta/openai (Gemini) |
                        https://api.openai.com/v1 | https://api.anthropic.com/v1 |
                        https://openrouter.ai/api/v1 | http://localhost:11434/v1 (Ollama)
  CHIMERA_LLM_API_KEY   (falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY; omit for keyless local)
  CHIMERA_LLM_MODEL     gemini-2.5-pro | gpt-4o | claude-opus-4-8 | qwen2.5-coder | llava | ...
"""
from __future__ import annotations
import os, json, base64, urllib.request, urllib.error
from pathlib import Path

from scripts.agent.judge import Judge, Verdict, parse_verdict, consensus_verdict


class LLMConfigError(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class LLMClient:
    """OpenAI-compatible chat client over stdlib HTTP. `_opener` is the test seam (urlopen)."""

    def __init__(self, *, base_url=None, api_key=None, model=None, timeout=180):
        self.base_url = (base_url or os.environ.get("CHIMERA_LLM_BASE_URL") or "").rstrip("/")
        self.api_key = (api_key or os.environ.get("CHIMERA_LLM_API_KEY")
                        or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model or os.environ.get("CHIMERA_LLM_MODEL")
        self.timeout = timeout
        if not self.base_url:
            raise LLMConfigError(
                "set CHIMERA_LLM_BASE_URL (e.g. https://api.openai.com/v1, https://api.anthropic.com/v1, "
                "https://openrouter.ai/api/v1, or http://localhost:11434/v1 for Ollama)")
        if not self.model:
            raise LLMConfigError("set CHIMERA_LLM_MODEL (e.g. gpt-4o, claude-opus-4-8, or a local model name)")

    def chat(self, messages, *, max_tokens=2048, temperature=0.4, _opener=urllib.request.urlopen) -> str:
        body = {"model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": temperature}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
        try:
            with _opener(req, timeout=self.timeout) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:   # surface the response body — providers put the real reason there
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise LLMError(f"LLM request to {self.base_url} failed: HTTP {e.code} {body}".rstrip()) from e
        except Exception as e:   # noqa: BLE001 - any other transport/parse failure surfaces as LLMError
            raise LLMError(f"LLM request to {self.base_url} failed: {e}") from e
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected LLM response shape: {str(resp)[:300]}") from e

    @staticmethod
    def _image_part(image_path):
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}

    def vision(self, prompt, image_path, **kw) -> str:
        """One vision turn: a text prompt + an inlined image (OpenAI image_url shape)."""
        return self.chat([{"role": "user",
                           "content": [{"type": "text", "text": prompt}, self._image_part(image_path)]}], **kw)


def client_for_role(role, *, cli_base=None, cli_model=None,
                    shared_cli_base=None, shared_cli_model=None, timeout=180) -> "LLMClient":
    """Build an LLMClient for `role` in {'codegen','judge','rewriter'}. SPECIFIC-WINS precedence for each
    of base_url/model:  role CLI > role env (CHIMERA_<ROLE>_*) > shared CLI (--llm-*) > shared env
    (CHIMERA_LLM_*).  api_key: CHIMERA_<ROLE>_API_KEY > CHIMERA_LLM_API_KEY > OPENAI_API_KEY > ANTHROPIC_API_KEY.
    Raises a role-tagged LLMConfigError (with an 'or run interactively' hint) when base_url/model can't be
    resolved, so the user knows which endpoint is missing and that an interactive agent is the alternative."""
    pre = "CHIMERA_" + role.upper()
    base = cli_base or os.environ.get(pre + "_BASE_URL") or shared_cli_base or os.environ.get("CHIMERA_LLM_BASE_URL")
    model = cli_model or os.environ.get(pre + "_MODEL") or shared_cli_model or os.environ.get("CHIMERA_LLM_MODEL")
    key = (os.environ.get(pre + "_API_KEY") or os.environ.get("CHIMERA_LLM_API_KEY")
           or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    try:
        return LLMClient(base_url=base, api_key=key, model=model, timeout=timeout)
    except LLMConfigError as e:
        raise LLMConfigError("[" + role + "] " + str(e)
                             + "  (or drive the loop interactively with an AI agent, which supersedes this)") from e


class LLMJudge(Judge):
    """Autonomous AI judge (#2): N vision passes over the rubric, combined via the existing
    consensus machinery. Drop-in `Judge` for run_loop — `--backend api` selects it over the local Qwen."""

    def __init__(self, client: LLMClient, *, passes: int = 1, temperature: float = 0.3):
        self.client = client
        self.passes = max(1, passes)
        self.temperature = temperature

    def judge(self, image_path, rubric) -> Verdict:
        prompt = rubric.as_prompt()
        texts = [self.client.vision(prompt, image_path, temperature=self.temperature)
                 for _ in range(self.passes)]
        return parse_verdict(texts[0]) if self.passes == 1 else consensus_verdict(texts)


_CAD_SYSTEM = (
    "You are an expert FreeCAD modeller. Write a single self-contained FreeCAD Python script that builds "
    "the requested object as clean parametric BREP solids. The script runs headless with `App` (FreeCAD), "
    "`Part`, `Mesh`, and an active document `doc` already in scope — do NOT import or create a document. "
    "FreeCAD API: vectors are `App.Vector(x, y, z)` — NEVER `Part.Vector`; make solids with "
    "`Part.makeBox/makeCylinder/makeSphere/makeCone`; combine via `.fuse(o)`, `.cut(o)`, `.common(o)`; "
    "move via `shape.translate(App.Vector(dx, dy, dz))`. "
    "Build geometry as Part objects added to `doc` (e.g. `o = doc.addObject('Part::Feature','X'); "
    "o.Shape = <shape>`), OR set a module global `RESULT` to the list of shapes to export "
    "(e.g. `RESULT = [my_solid]` where my_solid is a Part shape from makeBox/cut/fuse). Use millimetres. "
    "Prefer booleans/fillets for a manufacturable single solid. Output ONLY one ```python code block``` "
    "and no prose."
)


def _extract_code(text: str) -> str:
    """Pull the python from a ```python ...``` block; fall back to the raw text if unfenced."""
    if "```" in text:
        block = text.split("```", 2)
        if len(block) >= 2:
            body = block[1]
            if body.lower().startswith("python"):
                body = body[len("python"):]
            return body.strip("\n")
    return text.strip()


class LLMCadGenerator:
    """Autonomous CAD code-gen (#1): write/revise a FreeCAD script from the brief + the loop's FIX
    feedback. Keeps the previous script so each iteration REVISES rather than starts over."""

    def __init__(self, client: LLMClient, *, temperature: float = 0.5):
        self.client = client
        self.temperature = temperature
        self.prev: str | None = None

    def generate_script(self, brief: str, fix_feedback: str | None = None) -> str:
        if self.prev:
            user = (f"Revise this FreeCAD script so the result better matches the brief and fixes the "
                    f"feedback.\nBRIEF: {brief}\nFEEDBACK: {fix_feedback or '(refine quality and proportions)'}"
                    f"\n\nPREVIOUS SCRIPT:\n{self.prev}\n\nReturn the full revised script.")
        else:
            user = f"Create a parametric FreeCAD script for: {brief}."
        code = _extract_code(self.client.chat(
            [{"role": "system", "content": _CAD_SYSTEM}, {"role": "user", "content": user}],
            max_tokens=2048, temperature=self.temperature))
        self.prev = code
        return code
