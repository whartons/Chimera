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
  CHIMERA_LLM_MODEL     gemini-2.5-pro | gpt-4o | claude-opus-4-8 | qwen3.8:27b | qwen3-vl:8b-instruct | ...
                        (unset: Chimera's local model for the GPU's tier, see LOCAL_TIERS. A thinking model
                        must run with thinking off as the judge, or it spends the token budget on reasoning
                        and returns empty content — see chat() empty guard and reasoning_effort)
  CHIMERA_LLM_REASONING_EFFORT  optional `reasoning_effort` sent with every request (none | low | medium |
                        high; per role: CHIMERA_<ROLE>_REASONING_EFFORT). Unset = not sent. When a reply is
                        all reasoning and no content, chat() retries once with "none" and keeps it — the
                        fix for hybrid-thinking models served thinking-ON (e.g. Qwen3.x on Ollama >= 0.40).
"""
from __future__ import annotations
import os, re, sys, json, base64, urllib.parse, urllib.request, urllib.error
from pathlib import Path

from scripts.agent.judge import Judge, Verdict, parse_verdict, consensus_verdict, strip_thinking
from scripts.agent.expander import PromptExpander, TemplatedExpander
from scripts.brandkit import gpu


class LLMConfigError(RuntimeError):
    pass


# Chimera's own local models on Ollama, used for a role only when nothing is configured for it. They were
# chosen on an RTX 5090 (32 GB), and most cards have less, so they come in tiers picked from the GPU's memory
# (--llm-tier / CHIMERA_LLM_TIER overrides). Each role is (model, reasoning_effort): the hybrid thinking
# models run with thinking off, as benchmarked; the -instruct models don't think. Code-gen is Qwen 3.8 27B in
# every tier: the lighter Qwen 3.5 9B built none of the CAD test parts, so a smaller card runs the 27B partly
# on the CPU instead (slower, still right). The 2026-10 measurements (34-case judge set, CAD parts) are in
# modules/agent/self-correction.md.
# The large tier starts at 32 GB cards (they report about 31.8 GiB): beside ComfyUI's image model a 24 GB card has
# no room for the 27B judge (about 22 GB with its context cache), so ComfyUI would have to empty itself before every
# judgment, and with the desktop's own few GB in use the room never came (2026-10 review). The medium tier starts at
# 12 GB cards (about 11.99 GiB): at 11 an 11 GB card (11.00 GiB) got it, under 12 GB is the small tier (2026-10-25).
LOCAL_TIERS = {
    "large": {"min_gb": 28, "judge": ("qwen3.8:27b", "none"), "codegen": ("qwen3.8:27b", "none"),
              "rewriter": ("qwen3.8:27b", "none")},
    "medium": {"min_gb": 11.5, "judge": ("qwen3-vl:8b-instruct", None), "codegen": ("qwen3.8:27b", "none"),
               "rewriter": ("qwen3-vl:8b-instruct", None)},
    "small": {"min_gb": 0, "judge": ("qwen3-vl:4b-instruct", None), "codegen": ("qwen3.8:27b", "none"),
              "rewriter": ("qwen3-vl:4b-instruct", None)},
}
UNKNOWN_GPU_TIER = "medium"   # no GPU size readable (no ComfyUI, no nvidia-smi): a middle guess, said aloud


def local_tier(gpu_gb=None, override=None):
    """The local-model tier: an explicit choice (--llm-tier, else $CHIMERA_LLM_TIER; 'auto' means pick), else
    the largest tier whose minimum the GPU meets, else UNKNOWN_GPU_TIER. Thresholds sit under the nominal sizes,
    since a card reports a little less (a 32 GB card about 31.8 GiB, a 12 GB card about 11.99)."""
    name = (override or os.environ.get("CHIMERA_LLM_TIER") or "").strip().lower()
    if name and name != "auto":
        if name not in LOCAL_TIERS:
            raise LLMConfigError(f"unknown LLM tier {name!r}; expected auto, {', '.join(LOCAL_TIERS)}")
        return name
    if gpu_gb is None:
        return UNKNOWN_GPU_TIER
    return next(t for t, spec in LOCAL_TIERS.items() if gpu_gb >= spec["min_gb"])


def tier_models(tier):
    """The distinct models a tier uses, for doctor's pull check."""
    return sorted({LOCAL_TIERS[tier][role][0] for role in ("judge", "codegen", "rewriter")})


def default_local_base():
    return gpu.ollama_root() + "/v1"


def local_model_checks(comfy_client, ollama_url=None, _opener=urllib.request.urlopen):
    """Doctor lines for the agent loops' local models: the tier this GPU gets and whether Ollama has them."""
    gb = gpu.total_memory_gb(comfy_client)
    try:
        tier = local_tier(gb)
    except LLMConfigError as e:
        return [("warn", str(e))]
    spec = LOCAL_TIERS[tier]
    size = f"{gb:.0f} GB GPU" if gb else "GPU size unknown"
    out = [("info", f"agent loop local models: {tier} tier ({size}): judge {spec['judge'][0]}, code-gen "
                    f"{spec['codegen'][0]}, rewriter {spec['rewriter'][0]} (--llm-tier / CHIMERA_LLM_TIER to change)")]
    root = gpu.ollama_root(ollama_url)
    if not gpu.is_ollama(root, _opener=_opener):
        return out   # gpu_checks already reports a stopped Ollama
    missing = [m for m in tier_models(tier) if m not in set(gpu.pulled_models(root, _opener=_opener))]
    if missing:
        out.append(("warn", f"not pulled yet: {', '.join(missing)} (run: "
                            + " && ".join(f"ollama pull {m}" for m in missing) + ")"))
    else:
        out.append(("ok", f"the {tier} tier's models are pulled"))
    return out


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


_UNLOAD_WAIT = 10.0   # seconds release() waits for Ollama to let go of a model before a ComfyUI render


def _text(content):
    """A reply's `content` as text: a string, or a list of parts (some OpenAI-compatible servers send those), whose
    text parts are joined and whose others (a 'thinking' part, an image) dropped. .strip() on a list raised
    AttributeError past the LLMError handling (2026-10-25 review); any other type is a shape error (TypeError)."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else p.get("text") or "" for p in content
                       if isinstance(p, str) or (isinstance(p, dict) and p.get("type", "text") in ("text", "output_text")))
    raise TypeError(f"content is a {type(content).__name__}")


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
        self._ollama = None   # is base_url a local Ollama? probed until it says yes (_ollama_root)
        if not self.base_url:
            raise LLMConfigError(
                "set CHIMERA_LLM_BASE_URL (e.g. https://api.openai.com/v1, https://api.anthropic.com/v1, "
                "https://openrouter.ai/api/v1, or http://localhost:11434/v1 for Ollama)")
        if not self.model:
            raise LLMConfigError("set CHIMERA_LLM_MODEL (e.g. gpt-4o, claude-opus-4-8, or a local model name)")
        scheme, host, _ = _origin(self.base_url)
        if self.api_key and scheme == "http" and not gpu.is_local(self.base_url):
            print(f"warning: the LLM API key goes to {host} unencrypted (http://); use https", file=sys.stderr)
        # set by the agent loops: frees ComfyUI's VRAM before this model loads in a local Ollama (gpu.make_room),
        # called as make_room(full_bytes, floor_bytes)
        self.make_room = None
        self._planned = None   # the full-context bytes the room check planned for, checked after the load

    def chat(self, messages, *, max_tokens=2048, temperature=0.4, reject_truncated=False,
             _opener=urllib.request.urlopen) -> str:
        """The reply's text. `reject_truncated` (the judge): a reply cut off at max_tokens raises LLMError instead of
        coming back as a fragment, and one cut off while thinking gets the thinking-off retry."""
        self._ensure_room(_opener)
        content = self._chat(messages, max_tokens, temperature, reject_truncated, _opener)
        self._check_planned(_opener)
        return content

    def _chat(self, messages, max_tokens, temperature, reject_truncated, _opener) -> str:
        try:
            return self._chat_once(messages, max_tokens, temperature, self.reasoning_effort, _opener,
                                   reject_truncated=reject_truncated)
        except _ThinkingExhausted as first:
            if self.reasoning_effort is not None:   # an explicit setting is respected, never overridden
                raise
            try:   # hybrid-thinking model served thinking-ON: one retry with thinking switched off
                content = self._chat_once(messages, max_tokens, temperature, "none", _opener,
                                          reject_truncated=reject_truncated)
            except LLMError:   # the provider rejects the knob, or it didn't help: report the real cause
                raise LLMError(f"{first} (a retry with reasoning_effort='none' also failed)") from None
            self.reasoning_effort = "none"   # sticky: later calls skip the wasted thinking pass
            return content

    def _chat_once(self, messages, max_tokens, temperature, reasoning_effort, _opener, *, reject_truncated=False) -> str:
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
            content = _text(msg.get("content"))
        except (KeyError, IndexError, TypeError, AttributeError) as e:   # message: null used to escape as AttributeError
            raise LLMError(f"unexpected LLM response shape: {str(resp)[:300]}") from e
        fr = ch.get("finish_reason")
        if reject_truncated and content and fr == "length":
            # a judge reply cut off at max_tokens is a fragment: "...So overall this should PASS. Let me double check"
            # parsed as a PASS on servers that inline <think> (2026-10-25 review)
            if msg.get("reasoning") or msg.get("reasoning_content") or not strip_thinking(content).strip():
                raise _ThinkingExhausted(
                    f"LLM at {self.base_url} was cut off at max_tokens while thinking (finish_reason=length): use a "
                    "non-thinking '-instruct' model, turn thinking off with CHIMERA_<ROLE>_REASONING_EFFORT=none, or "
                    "raise max_tokens.")
            raise LLMError(f"LLM at {self.base_url} was cut off at max_tokens (finish_reason=length), so its reply is "
                           "a fragment and isn't judged; raise max_tokens or use a model that answers shorter.")
        if not (content and content.strip()):
            # A "thinking" model (e.g. the Ollama qwen3-vl:8b tag, vs qwen3-vl:8b-instruct) can spend
            # the WHOLE max_tokens budget on its separate `reasoning` field and return empty `content`
            # (finish_reason='length'). Surface that loudly: an empty string flowing downstream is a
            # silent failure — the judge would score a perfect render 0.0 with no clue why.
            rlen = len(msg.get("reasoning") or msg.get("reasoning_content") or "")
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
        """The Ollama root when base_url is a LOCAL Ollama server (only those share this GPU), else None. Probed
        until it answers, since one failed probe (Ollama restarting or starting late) used to turn the GPU checks
        off for the whole run. Raises gpu.ProbeError when it can't tell: a local server that took the connection
        but didn't answer is maybe an Ollama holding memory, where a refused connection is one that isn't running."""
        if not gpu.is_local(self.base_url):
            return None
        root = gpu.ollama_root(self.base_url)
        if not self._ollama:
            self._ollama = gpu.is_ollama(root, _opener=_opener, strict=True)
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
        would load onto the full card regardless (it can't see ComfyUI's memory), and that froze a PC. Also when
        a local Ollama doesn't answer (a timeout, not a refused connection): what it holds is unknown, and a
        timed-out probe used to read as "not running" or "nothing loaded" (2026-10-25 review)."""
        if self.make_room is None or not gpu.is_local(self.base_url):
            return
        try:
            root = self._ollama_root(_opener)
            if root is None:
                return   # not Ollama, or not running: the request fails without loading anything
            loaded = gpu.loaded_models(root, _opener=_opener, strict=True)
            if any(gpu.same_model(n, self._ollama_name()) for n, _ in loaded):
                return
            need = gpu.vram_need_range(root, self._ollama_name(), _opener=_opener, strict=True)
        except gpu.ProbeError as e:
            raise LLMError(f"not loading {self.model}: {e}, so the GPU check can't tell what Ollama holds. Retry once "
                           "it answers (restart Ollama if it's stuck).") from None
        if not need:
            return   # Ollama doesn't have the model, so the request fails without loading anything
        floor, full = need
        self._planned = full
        # On Windows ComfyUI can't see the models already resident in Ollama either (another role's, say), so
        # the room it reports must cover them too. Elsewhere the driver's free figure already counts them.
        held = sum(v for _, v in loaded) if sys.platform == "win32" else 0
        if self.make_room(full + held, floor + held) is False:
            raise LLMError(f"not loading {self.model}: the GPU has no room for it even after asking ComfyUI to "
                           f"unload its models (it needs about {(floor + held) / 2**30:.0f} GB at a 32k context"
                           f"{', with the models Ollama already holds' if held else ''}). Close other GPU apps or "
                           "run `python scripts/generate.py free`, then retry.")

    def _check_planned(self, _opener=urllib.request.urlopen):
        """After a load the room check sized, warn when Ollama took more than planned. The estimate reads Ollama's
        settings (OLLAMA_KV_CACHE_TYPE, OLLAMA_CONTEXT_LENGTH, OLLAMA_FLASH_ATTENTION) from Chimera's own
        environment, so a server started with others is the one way it can still come out low."""
        planned, self._planned = self._planned, None
        if not planned or not self._ollama:
            return
        size = next((v for n, v in gpu.loaded_models(gpu.ollama_root(self.base_url), _opener=_opener)
                     if gpu.same_model(n, self._ollama_name())), 0)
        if size > planned:
            print(f"warning: Ollama loaded {self.model} at {size / 2**30:.1f} GB, more than the {planned / 2**30:.1f} "
                  "GB the GPU check planned for. Chimera reads OLLAMA_KV_CACHE_TYPE, OLLAMA_CONTEXT_LENGTH and "
                  "OLLAMA_FLASH_ATTENTION from its own environment: set them where Ollama runs too (as user "
                  "environment variables, say), so the check sizes models right", file=sys.stderr)

    def resident(self, _opener=urllib.request.urlopen) -> bool:
        """True when this client's model is loaded in a local Ollama, or may be: one that doesn't answer (a
        timeout, not a refused connection) can't say it let go, so the loops don't render beside it."""
        try:
            root = self._ollama_root(_opener)
            return root is not None and gpu.is_resident(root, self._ollama_name(), _opener=_opener, strict=True)
        except gpu.ProbeError:
            return True

    def release(self, _opener=urllib.request.urlopen) -> bool:
        """Hand the GPU back: if base_url is a local Ollama and this client's model is resident, unload
        it now (keep_alive 0) instead of letting it sit for Ollama's ~5-minute keep-alive, and wait until
        Ollama no longer lists it. The loops call this before each ComfyUI render. Only a RESIDENT model is
        unloaded (Ollama may load a missing one to unload it). No-op for hosted and remote endpoints (another
        machine's Ollama doesn't share this GPU) or with CHIMERA_KEEP_LLM_LOADED=1; never raises. True when it
        unloaded the model."""
        if gpu.keep_llms_loaded():
            return False
        try:
            root = self._ollama_root(_opener)
        except gpu.ProbeError:
            return False   # can't tell; resident() then says it may be loaded, and the render waits
        if root is None or not gpu.is_resident(root, self._ollama_name(), _opener=_opener):
            return False
        return gpu.unload(root, self._ollama_name(), wait=_UNLOAD_WAIT, _opener=_opener)

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
                    default_base=None, default_model=None, default_reasoning=None, timeout=180) -> LLMClient:
    """Build an LLMClient for `role` in {'codegen','judge','rewriter'}. SPECIFIC-WINS precedence for each
    of base_url/model/reasoning_effort:  role CLI > role env (CHIMERA_<ROLE>_*) > shared CLI (--llm-*) >
    shared env (CHIMERA_LLM_*) > the caller's default_base/default_model (Chimera's local Ollama model);
    default_reasoning applies only when the model itself is that default (a configured model is never sent it).  api_key: CHIMERA_<ROLE>_API_KEY > CHIMERA_LLM_API_KEY (only on the shared
    endpoint's host) > the vendor's own OPENAI_API_KEY / ANTHROPIC_API_KEY for its own host (`resolve_key`).
    Raises a role-tagged LLMConfigError (with an 'or run interactively' hint) when base_url/model can't be
    resolved, so the user knows which endpoint is missing and that an interactive agent is the alternative."""
    pre = "CHIMERA_" + role.upper()
    base = (cli_base or os.environ.get(pre + "_BASE_URL") or shared_cli_base or os.environ.get("CHIMERA_LLM_BASE_URL")
            or default_base)
    chosen = cli_model or os.environ.get(pre + "_MODEL") or shared_cli_model or os.environ.get("CHIMERA_LLM_MODEL")
    model = chosen or default_model
    key = resolve_key(base, role_key=os.environ.get(pre + "_API_KEY"),
                      shared_base=shared_cli_base or os.environ.get("CHIMERA_LLM_BASE_URL"))
    effort = (cli_reasoning or os.environ.get(pre + "_REASONING_EFFORT") or shared_cli_reasoning
              or os.environ.get("CHIMERA_LLM_REASONING_EFFORT") or (None if chosen else default_reasoning))
    if base and not key and not gpu.is_local(base):
        # keys stay with their own host since v0.6.0: a v0.5 setup (OpenRouter + OPENAI_API_KEY) now got HTTP
        # 401 on every iteration, after the render, with nothing said
        held = [env for env in _VENDOR_KEYS.values() if os.environ.get(env)]
        if os.environ.get("CHIMERA_LLM_API_KEY"):
            held.append("CHIMERA_LLM_API_KEY (it follows only the shared endpoint)")
        if held:
            print(f"note: [{role}] no API key goes to {_origin(base)[1]}: {', '.join(held)} isn't sent there. If "
                  f"it needs one, set {pre}_API_KEY (or CHIMERA_LLM_API_KEY for a shared endpoint)", file=sys.stderr)
    try:
        client = LLMClient(base_url=base, api_key=key or "", model=model, timeout=timeout, reasoning_effort=effort)
        client.from_default = not chosen   # the run says which models it fell back to
        return client
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
        # a reply cut off at max_tokens fails the iteration rather than pass on a fragment
        texts = [self.client.vision(prompt, image_path, temperature=self.temperature, reject_truncated=True)
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
    "The part must come out as ONE connected solid (pieces that don't touch fail the check): every feature you "
    "fuse on must overlap the body, not float in an open cavity or above it. A cut only removes material that "
    "is there: cut recesses, sockets and holes into solid material (before hollowing a body, or into a floor or "
    "block thick enough to hold them), never into an existing cavity, where they vanish. "
    "Output ONLY one ```python code block``` and no prose."
)


_FENCE_TAG = re.compile(r"[\w+.#-]*[ \t]*\n")   # a fence's language tag ('python', 'py', 'Python3') to its newline


def _extract_code(text: str) -> str:
    """Pull the python from a ```python ...``` block; fall back to the raw text if unfenced."""
    if "```" in text:
        block = text.split("```", 2)
        if len(block) >= 2:
            # any tag, not just 'python': a ```py fence left "py" as the script's first line (2026-10-25 review)
            body = _FENCE_TAG.sub("", block[1], count=1) if _FENCE_TAG.match(block[1]) else block[1]
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
            if fix_feedback:   # a first script was rejected: say why, or the retry repeats it
                user += f"\nFeedback on an earlier attempt: {fix_feedback}"
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
