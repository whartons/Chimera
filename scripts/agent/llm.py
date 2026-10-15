"""Provider-agnostic LLM backend for the agent loop — autonomous AI judge (#2) and CAD code-gen (#1).

Targets the **OpenAI-compatible `/v1/chat/completions`** shape, the de-facto lingua franca, so ONE
implementation works with **Google Gemini**, OpenAI, **Anthropic's OpenAI-compat endpoint**, OpenRouter,
Together, Groq, or a **local** server (Ollama / LM Studio / vLLM / llama.cpp). No vendor SDK — pure stdlib
urllib/json/base64 (zero new deps, CI-safe). Vision uses the OpenAI `image_url` data-URI part.

Config (env, with CLI overrides; no hardcoded vendor default):
  CHIMERA_LLM_BASE_URL  https://generativelanguage.googleapis.com/v1beta/openai (Gemini) |
                        https://api.openai.com/v1 | https://api.anthropic.com/v1 |
                        https://openrouter.ai/api/v1 | http://localhost:11434/v1 (Ollama)
  CHIMERA_LLM_API_KEY   sent only to CHIMERA_LLM_BASE_URL's host (else OPENAI_API_KEY / ANTHROPIC_API_KEY,
                        but only to https://api.openai.com / https://api.anthropic.com; omit for keyless local)
  CHIMERA_LLM_MODEL     gemini-2.5-pro | gpt-4o | claude-opus-4-8 | qwen3.6-27b | qwen3-vl:8b-instruct | ...
                        (use a NON-thinking '-instruct' VLM as the judge: a thinking model spends the
                        token budget on reasoning and returns empty content — see chat() empty guard)
  CHIMERA_LLM_REASONING_EFFORT  optional `reasoning_effort` sent with every request (none | low | medium |
                        high; per role: CHIMERA_<ROLE>_REASONING_EFFORT). Unset = not sent. When a reply is
                        all reasoning and no content, chat() retries once with "none" and keeps it — the
                        fix for hybrid-thinking models served thinking-ON (e.g. Qwen3.x on Ollama >= 0.40).
"""
from __future__ import annotations
import os, sys, json, base64, urllib.parse, urllib.request, urllib.error
from pathlib import Path

from scripts.agent.judge import Judge, Verdict, parse_verdict, consensus_verdict
from scripts.agent.expander import PromptExpander, TemplatedExpander
from scripts.brandkit import gpu


class LLMConfigError(RuntimeError):
    pass


# The judge's out-of-the-box endpoint: the recommended local setup, Ollama serving Qwen3-VL-8B-Instruct
# (non-thinking). Used only when no judge or shared endpoint/model is configured.
DEFAULT_JUDGE_MODEL = "qwen3-vl:8b-instruct"


def default_judge_base():
    return gpu.ollama_root() + "/v1"


# A vendor's own env key only ever goes to that vendor. Before 2026-10, with no CHIMERA_* key set, an
# OPENAI_API_KEY (often exported globally for other tools) was sent to ANY base URL: OpenRouter, Gemini,
# a LAN box, a typo'd host.
_VENDOR_KEYS = {"api.openai.com": "OPENAI_API_KEY", "api.anthropic.com": "ANTHROPIC_API_KEY"}


def _origin(url):
    u = urllib.parse.urlparse(url or "")
    return u.scheme.lower(), (u.hostname or "").lower(), u.port


def vendor_key(base_url):
    """OPENAI_API_KEY for an https://api.openai.com base URL, ANTHROPIC_API_KEY for https://api.anthropic.com,
    else None."""
    scheme, host, _ = _origin(base_url)
    env = _VENDOR_KEYS.get(host) if scheme == "https" else None
    return os.environ.get(env) if env else None


def resolve_key(base_url, *, role_key=None, shared_base=None):
    """The API key to send to `base_url`: a role's own key, else CHIMERA_LLM_API_KEY when base_url is on the
    shared endpoint's origin (or no shared endpoint is set), else the vendor's own key for its own host. A
    shared OpenAI key used to follow a role pointed at OpenRouter or a LAN box (2026-10 audit)."""
    shared = os.environ.get("CHIMERA_LLM_API_KEY")
    if shared and shared_base and _origin(shared_base) != _origin(base_url):
        shared = None
    return role_key or shared or vendor_key(base_url)




class LLMError(RuntimeError):
    pass


class _ThinkingExhausted(LLMError):
    """Empty content because a thinking model spent the whole budget on reasoning (triggers the retry)."""


class LLMClient:
    """OpenAI-compatible chat client over stdlib HTTP. `_opener` is the test seam (urlopen)."""

    def __init__(self, *, base_url=None, api_key=None, model=None, timeout=180, reasoning_effort=None):
        self.base_url = (base_url or os.environ.get("CHIMERA_LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key if api_key is not None else resolve_key(
            self.base_url, shared_base=os.environ.get("CHIMERA_LLM_BASE_URL"))
        self.model = model or os.environ.get("CHIMERA_LLM_MODEL")
        self.timeout = timeout
        effort = (reasoning_effort or os.environ.get("CHIMERA_LLM_REASONING_EFFORT") or "").strip().lower()
        self.reasoning_effort = effort or None
        self._ollama = None   # is base_url a local Ollama? probed once, by release()
        if not self.base_url:
            raise LLMConfigError(
                "set CHIMERA_LLM_BASE_URL (e.g. https://api.openai.com/v1, https://api.anthropic.com/v1, "
                "https://openrouter.ai/api/v1, or http://localhost:11434/v1 for Ollama)")
        if not self.model:
            raise LLMConfigError("set CHIMERA_LLM_MODEL (e.g. gpt-4o, claude-opus-4-8, or a local model name)")
        scheme, host, _ = _origin(self.base_url)
        if self.api_key and scheme == "http" and not gpu.is_local(self.base_url):
            print(f"warning: the LLM API key goes to {host} unencrypted (http://); use https", file=sys.stderr)
        # set by the agent loops: frees ComfyUI's VRAM before this model loads in a local Ollama (gpu.make_room)
        self.make_room = None

    def chat(self, messages, *, max_tokens=2048, temperature=0.4, _opener=urllib.request.urlopen) -> str:
        self._ensure_room(_opener)
        try:
            return self._chat_once(messages, max_tokens, temperature, self.reasoning_effort, _opener)
        except _ThinkingExhausted as first:
            if self.reasoning_effort is not None:   # an explicit setting is respected, never overridden
                raise
            try:   # hybrid-thinking model served thinking-ON: one retry with thinking switched off
                content = self._chat_once(messages, max_tokens, temperature, "none", _opener)
            except LLMError:   # the provider rejects the knob, or it didn't help: report the real cause
                raise LLMError(f"{first} (a retry with reasoning_effort='none' also failed)") from None
            self.reasoning_effort = "none"   # sticky: later calls skip the wasted thinking pass
            return content

    def _chat_once(self, messages, max_tokens, temperature, reasoning_effort, _opener) -> str:
        body = {"model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": temperature}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        if self.api_key:   # unredirected: urllib copies ordinary headers onto a redirect to any host
            req.add_unredirected_header("Authorization", f"Bearer {self.api_key}")
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
            ch = resp["choices"][0]
            msg = ch["message"]
            content = msg.get("content")
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected LLM response shape: {str(resp)[:300]}") from e
        if not (content and content.strip()):
            # A "thinking" model (e.g. the Ollama qwen3-vl:8b tag, vs qwen3-vl:8b-instruct) can spend
            # the WHOLE max_tokens budget on its separate `reasoning` field and return empty `content`
            # (finish_reason='length'). Surface that loudly: an empty string flowing downstream is a
            # silent failure — the judge would score a perfect render 0.0 with no clue why.
            rlen = len(msg.get("reasoning") or msg.get("reasoning_content") or "")
            fr = ch.get("finish_reason")
            if rlen or fr == "length":
                sent = f", reasoning_effort={reasoning_effort}" if reasoning_effort else ""
                raise _ThinkingExhausted(
                    f"LLM at {self.base_url} returned empty content — got {rlen} reasoning tokens but empty "
                    f"content (finish_reason={fr}{sent}): this is a 'thinking' model exhausting max_tokens. "
                    "Use a non-thinking '-instruct' model (e.g. qwen3-vl:8b-instruct), turn thinking off with "
                    "CHIMERA_<ROLE>_REASONING_EFFORT=none (or --<role>-reasoning-effort none), or raise max_tokens.")
            raise LLMError(f"LLM at {self.base_url} returned empty content")
        return content

    def _ollama_root(self, _opener):
        """The Ollama root when base_url is an Ollama server (probed once), else None."""
        root = gpu.ollama_root(self.base_url)
        if self._ollama is None:
            self._ollama = gpu.is_ollama(root, _opener=_opener)
        return root if self._ollama else None

    def _ollama_name(self):
        return self.model if ":" in self.model else self.model + ":latest"

    @property
    def ollama_name(self):
        """The model as Ollama lists it (an untagged name means ':latest')."""
        return self._ollama_name()

    def _ensure_room(self, _opener=urllib.request.urlopen):
        """Before a request that will load this model into a LOCAL Ollama, pass its memory need to make_room
        (set by the agent loops), so ComfyUI hands the GPU over first. No-op when unset, for hosted or remote
        endpoints, or when the model is already resident. Raises LLMError when the room never came: Ollama
        would load onto the full card regardless (it can't see ComfyUI's memory), and that froze a PC."""
        if self.make_room is None or not gpu.is_local(self.base_url):
            return
        root = self._ollama_root(_opener)
        if root is None or self._ollama_name() in {n for n, _ in gpu.loaded_models(root, _opener=_opener)}:
            return
        need = gpu.vram_need(root, self._ollama_name(), _opener=_opener)
        if need and self.make_room(need) is False:
            raise LLMError(f"not loading {self.model}: the GPU has no room for it (about {need / 2**30:.0f} GB) "
                           "even after asking ComfyUI to unload its models. Close other GPU apps or run "
                           "`python scripts/generate.py free`, then retry.")

    def release(self, _opener=urllib.request.urlopen) -> bool:
        """Hand the GPU back: if base_url is a local Ollama and this client's model is resident, unload
        it now (keep_alive 0) instead of letting it sit for Ollama's ~5-minute keep-alive. The loops call
        this before each ComfyUI render. Only a RESIDENT model is unloaded (Ollama may load a missing one
        to unload it). No-op for hosted APIs or with CHIMERA_KEEP_LLM_LOADED=1; never raises."""
        if gpu.keep_llms_loaded():
            return False
        root = self._ollama_root(_opener)
        if root is None or self._ollama_name() not in {n for n, _ in gpu.loaded_models(root, _opener=_opener)}:
            return False
        return gpu.unload(root, self._ollama_name(), _opener=_opener)

    @staticmethod
    def _image_part(image_path):
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}

    def vision(self, prompt, image_path, **kw) -> str:
        """One vision turn: a text prompt + an inlined image (OpenAI image_url shape)."""
        return self.chat([{"role": "user",
                           "content": [{"type": "text", "text": prompt}, self._image_part(image_path)]}], **kw)


def client_for_role(role, *, cli_base=None, cli_model=None, cli_reasoning=None,
                    shared_cli_base=None, shared_cli_model=None, shared_cli_reasoning=None,
                    default_base=None, default_model=None, timeout=180) -> LLMClient:
    """Build an LLMClient for `role` in {'codegen','judge','rewriter'}. SPECIFIC-WINS precedence for each
    of base_url/model/reasoning_effort:  role CLI > role env (CHIMERA_<ROLE>_*) > shared CLI (--llm-*) >
    shared env (CHIMERA_LLM_*) > the caller's default_base/default_model (the judge's local Ollama).  api_key: CHIMERA_<ROLE>_API_KEY > CHIMERA_LLM_API_KEY (only on the shared
    endpoint's host) > the vendor's own OPENAI_API_KEY / ANTHROPIC_API_KEY for its own host (`resolve_key`).
    Raises a role-tagged LLMConfigError (with an 'or run interactively' hint) when base_url/model can't be
    resolved, so the user knows which endpoint is missing and that an interactive agent is the alternative."""
    pre = "CHIMERA_" + role.upper()
    base = (cli_base or os.environ.get(pre + "_BASE_URL") or shared_cli_base or os.environ.get("CHIMERA_LLM_BASE_URL")
            or default_base)
    model = (cli_model or os.environ.get(pre + "_MODEL") or shared_cli_model or os.environ.get("CHIMERA_LLM_MODEL")
             or default_model)
    key = resolve_key(base, role_key=os.environ.get(pre + "_API_KEY"),
                      shared_base=shared_cli_base or os.environ.get("CHIMERA_LLM_BASE_URL"))
    effort = (cli_reasoning or os.environ.get(pre + "_REASONING_EFFORT") or shared_cli_reasoning
              or os.environ.get("CHIMERA_LLM_REASONING_EFFORT"))
    try:
        return LLMClient(base_url=base, api_key=key or "", model=model, timeout=timeout, reasoning_effort=effort)
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
    "move via `shape.translate(App.Vector(dx, dy, dz))`; rotate a copy via `s = shape.copy(); "
    "s.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), degrees)` (a Matrix has no `.rotate`). "
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


_REWRITE_SYSTEM = {
    "image": ("You are a prompt engineer for text-to-image generation. Rewrite the positive and negative "
              "prompts so the render better matches the subject and brand voice and fixes the critic's "
              "directives. Preserve the brand style and palette. Output ONLY JSON: "
              '{"positive": "...", "negative": "..."}'),
    "3d": ("You are a prompt engineer for image-to-3D / CAD concept generation. Rewrite the positive and "
           "negative prompts describing the object's FORM (one clean subject, neutral background, no text) "
           "so it better matches the subject and fixes the critic's directives. Output ONLY JSON: "
           '{"positive": "...", "negative": "..."}'),
}


def _rewrite_user(subject, seed_pos, seed_neg, prior_issues):
    fixes = "\n".join("- " + str(i) for i in (prior_issues or [])) or "(none — this is the first attempt)"
    return ("SUBJECT: " + subject + "\nCURRENT POSITIVE: " + seed_pos + "\nCURRENT NEGATIVE: " + seed_neg
            + "\nCRITIC FIX DIRECTIVES:\n" + fixes + "\n\nReturn improved JSON.")


def _extract_json(text):
    """Pull the first {...} object from the LLM output (tolerating a ```json fence). Raises on none."""
    s = text
    if "```" in s:
        parts = s.split("```", 2)
        if len(parts) >= 2:
            s = parts[1]
            if s.lower().startswith("json"):
                s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b < a:
        raise ValueError("no JSON object in LLM rewrite output")
    return json.loads(s[a:b + 1])


class LLMExpander(PromptExpander):
    """Rewrite (positive, negative) with an LLM from subject + brand voice + the judge's prior FIX
    directives. The templated expander SEEDS the rewrite AND is the fallback, so output never degrades
    below today's behavior and any LLM/parse failure is non-fatal. Text-only (no vision)."""

    def __init__(self, client, *, modality="image", fallback=None, temperature=0.5):
        self.client = client
        self.modality = "3d" if modality == "3d" else "image"
        self.fallback = fallback or TemplatedExpander()
        self.temperature = temperature

    def expand(self, subject, manifest, prior_issues=None):
        seed_pos, seed_neg = self.fallback.expand(subject, manifest, prior_issues)
        try:
            out = self.client.chat(
                [{"role": "system", "content": _REWRITE_SYSTEM[self.modality]},
                 {"role": "user", "content": _rewrite_user(subject, seed_pos, seed_neg, prior_issues)}],
                temperature=self.temperature)
            data = _extract_json(out)
            return (str(data["positive"]).strip() or seed_pos), (str(data.get("negative", seed_neg)).strip() or seed_neg)
        except Exception:   # noqa: BLE001 — rewriting is best-effort; never break the loop
            return seed_pos, seed_neg
