"""Judge interface + Verdict + a robust parser for a VLM's free-text judgment."""
from __future__ import annotations
import json, os, re, sys, time
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from scripts.brandkit.nodes import find_node_by_title


@dataclass
class Verdict:
    """A judge's decision: overall pass/fail, a 0-1 score, unmet-criterion issues."""
    passed: bool
    score: float
    issues: list = field(default_factory=list)


class Judge(ABC):
    """Scores an image against a rubric, returning a Verdict."""

    @abstractmethod
    def judge(self, image_path, rubric) -> Verdict:
        raise NotImplementedError


# standalone PASS / FAIL verdict tokens (word-boundaried, case-insensitive) so
# 'passable' / 'compass' / 'failsafe' never trip the overall verdict.
_PASS = re.compile(r"\bpass(?:ed)?\b", re.IGNORECASE)
_FAIL = re.compile(r"\bfail(?:ed)?\b", re.IGNORECASE)
_SCORE = re.compile(
    r"score[^\d\-]{0,4}(-?\d+(?:\.\d+)?)\s*(/\s*(\d+(?:\.\d+)?)|%)?", re.IGNORECASE)
# Issues are the rubric's genuine NOT-MET lines only. A plain 'MET - ...' line never
# contains 'not met', so MET criteria (even ones mentioning 'avoids'/'missing') are excluded.
_NOTMET = re.compile(r"\bnot[\s\-]?met\b|\bunmet\b", re.IGNORECASE)
# Also carry any line bearing a 'FIX:' directive (the judge's structured add/avoid correction) so
# the expander receives it even if the model puts it on its own line rather than the NOT-MET line.
_FIXLINE = re.compile(r"\bfix\b\s*[:\-]", re.IGNORECASE)


def parse_verdict(text: str) -> Verdict:
    """Parse a VLM judgment into a Verdict. Never raises."""
    try:
        if not text or not str(text).strip():
            return Verdict(passed=False, score=0.0, issues=[])
        text = str(text)
        lines = text.splitlines()

        # Decide PASS/FAIL from the verdict-bearing line only, so criterion
        # reasons containing the word 'fail' (or 'pass') don't contaminate the
        # overall verdict. The rubric asks the judge to put the overall verdict
        # on its own line; prefer that line, else the last standalone PASS/FAIL.
        verdict_line = next(
            (l for l in lines if "overall" in l.lower()
             and (_PASS.search(l) or _FAIL.search(l))),
            None,
        )
        if verdict_line is None:
            verdict_line = next(
                (l for l in reversed(lines) if _PASS.search(l) or _FAIL.search(l)),
                "",
            )
        # FAIL takes precedence; PASS only on an explicit standalone token.
        failed = bool(_FAIL.search(verdict_line))
        passed = bool(_PASS.search(verdict_line)) and not failed

        m = _SCORE.search(text)
        if m:
            val = float(m.group(1))
            if m.group(3):                                  # "value/denom"
                d = float(m.group(3)); val = val / d if d else 0.0
            elif m.group(2) and m.group(2).strip() == "%":  # "value%"
                val = val / 100.0
            score = max(0.0, min(1.0, val))
        else:
            score = 0.0

        issues = []
        for line in lines:
            seg = line.strip()
            # Collect genuine NOT-MET lines (and any standalone FIX: directive line); skip the
            # overall verdict line so a real 'Overall: FAIL' isn't threaded back as noise.
            if seg and "overall" not in seg.lower() and (_NOTMET.search(seg) or _FIXLINE.search(seg)):
                issues.append(seg)

        return Verdict(passed=passed, score=score, issues=issues)
    except Exception as e:
        print(f"[agent] parse_verdict failed: {e}", file=sys.stderr)
        return Verdict(passed=False, score=0.0, issues=["unparseable verdict"])


_TEMPLATE = "agent-vlm-judge.json"


class LocalVLMJudge(Judge):
    """Judge an image with Qwen2.5-VL run as a ComfyUI graph (1038lab/ComfyUI-QwenVL).
    Fills agent-vlm-judge.json (uploaded image + rubric.as_prompt()), queues it, reads the
    verdict text the graph wrote via SaveImageTextDataSetToFolder, and parses it."""

    def __init__(self, client, repo_root, comfy_output_dir, *, timeout=600,
                 _read_retries=5, _read_delay=0.4):
        self.client = client
        self.repo_root = Path(repo_root)
        self.comfy_output_dir = Path(comfy_output_dir)
        self.timeout = timeout
        self._read_retries = _read_retries
        self._read_delay = _read_delay
        self._n = 0  # per-instance call counter -> run-unique filename_prefix

    def _load_template(self) -> dict:
        p = self.repo_root / "workflows" / "templates" / _TEMPLATE
        return json.loads(p.read_text(encoding="utf-8"))

    def _read_verdict(self, prefix) -> str | None:
        """Return the verdict text the graph wrote, or None. The node writes
        <output>/agent_verdicts/<prefix>_00000.txt; retry briefly for the FS flush
        (mirrors route_output's lock-retry), then fall back to the newest matching glob."""
        verdicts = self.comfy_output_dir / "agent_verdicts"
        exact = verdicts / f"{prefix}_00000.txt"
        for _ in range(max(1, self._read_retries)):
            if exact.exists():
                return exact.read_text(encoding="utf-8")
            matches = sorted(verdicts.glob(f"{prefix}_*.txt"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return matches[0].read_text(encoding="utf-8")
            time.sleep(self._read_delay)
        return None

    def judge(self, image_path, rubric) -> Verdict:
        uploaded = self.client.upload_image(Path(image_path))
        # Run-unique prefix (image stem + pid + per-instance counter) so a cross-run
        # same-seed collision can never feed back a stale verdict. Filesystem-safe.
        self._n += 1
        prefix = f"verdict_{Path(image_path).stem}_{os.getpid()}_{self._n}"

        wf = deepcopy(self._load_template())
        find_node_by_title(wf, "brand:vlm_image")[1]["inputs"]["image"] = uploaded
        find_node_by_title(wf, "brand:vlm")[1]["inputs"]["custom_prompt"] = rubric.as_prompt()
        find_node_by_title(wf, "brand:vlm_out")[1]["inputs"]["filename_prefix"] = prefix

        pid = self.client.queue_prompt(wf)
        self.client.wait(pid, max_wait=self.timeout)

        text = self._read_verdict(prefix)

        # The capture node also writes a (large, junk) <prefix>_*.png alongside the
        # verdict .txt; drop it best-effort (same glob as the .txt, so it still cleans
        # up if the index ever differs) so verdicts don't accumulate stray renders.
        for png in (self.comfy_output_dir / "agent_verdicts").glob(f"{prefix}_*.png"):
            try:
                png.unlink()
            except OSError:
                pass

        if text is None:
            return Verdict(passed=False, score=0.0,
                           issues=["judge produced no verdict file"])
        return parse_verdict(text)


class ConsensusJudge(Judge):
    """A judge panel: aggregate N sub-judges into one Verdict by majority vote. Each sub-judge
    scores the image independently; the panel combines them as
      passed  = at least `pass_threshold` sub-judges passed (strict majority by default),
      score   = mean of the sub-scores,
      issues  = de-duplicated union of every sub-judge's issues (so the expander addresses every
                raised concern on the next iteration).
    Judge-agnostic — the diversity comes from the judges you pass in (different VLMs, prompts, or an
    assistant panel), all behind the same `Judge` seam. A sub-judge that raises counts as a fail and
    never crashes the panel, so one flaky judge can't take the loop down."""

    def __init__(self, judges, *, pass_threshold=None):
        self.judges = list(judges)
        if not self.judges:
            raise ValueError("ConsensusJudge needs at least one judge")
        # strict majority: more than half must pass (N=2 -> unanimous; N=3 -> 2; N=5 -> 3)
        self.pass_threshold = pass_threshold if pass_threshold is not None \
            else (len(self.judges) // 2) + 1

    def judge(self, image_path, rubric) -> Verdict:
        verdicts = []
        for j in self.judges:
            try:
                verdicts.append(j.judge(image_path, rubric))
            except Exception as e:                     # one flaky judge != a dead panel
                verdicts.append(Verdict(passed=False, score=0.0, issues=[f"judge error: {e}"]))
        passes = sum(1 for v in verdicts if v.passed)
        score = sum(v.score for v in verdicts) / len(verdicts)
        seen, issues = set(), []
        for v in verdicts:
            for it in v.issues:
                if it not in seen:
                    seen.add(it); issues.append(it)
        return Verdict(passed=passes >= self.pass_threshold, score=round(score, 4), issues=issues)
