"""Judge interface + Verdict + a robust parser for a VLM's free-text judgment."""
from __future__ import annotations
import json, os, re, sys, time
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from scripts.brandkit.nodes import find_node_by_title
from scripts.agent.geometry import structural_issues, RENDER_CHECKS_SUFFIX


@dataclass
class Verdict:
    """A judge's decision: overall pass/fail, a 0-1 score, unmet-criterion issues. `geometry_failed`: a deterministic
    geometry check failed it (GeometryAwareJudge), whatever the score says; such a candidate ranks below any clean
    one (loop.run_loop)."""
    passed: bool
    score: float
    issues: list = field(default_factory=list)
    geometry_failed: bool = False


class Judge(ABC):
    """Scores an image against a rubric, returning a Verdict."""

    @abstractmethod
    def judge(self, image_path, rubric) -> Verdict:
        raise NotImplementedError


# standalone PASS / FAIL verdict tokens (word-boundaried, case-insensitive) so
# 'passable' / 'compass' / 'failsafe' never trip the overall verdict; a negated pass ('Does not pass') is a FAIL.
_PASS = re.compile(r"\bpass(?:ed)?\b", re.IGNORECASE)
# ... and so is a pass field set to no ('PASS: false', 'Passed: No', JSON's "passed": false), which read as a PASS;
# 'PASS: no issues found' isn't one (2026-10-25 review)
_FAIL = re.compile(r"\bfail(?:ed)?\b|(?:\bnot|\bnever|\bcannot|n't)\s+(?:a\s+)?pass(?:ed)?\b"
                   r"|\bpass(?:ed)?\b[\"'*_\s]*[:=][\"'*_\s]*(?:no|false|0(?!\.\d))\b(?=[\"'*_\s]*(?:[,;.}\])]|$))",
                   re.IGNORECASE)
# the reply format echoed as a label ('Overall (PASS/FAIL): PASS'): its FAIL isn't the verdict
_FORMAT_LABEL = re.compile(r"[(\[]?\s*\bpass\s*(?:/|\bor\b)\s*fail\b\s*[)\]]?", re.IGNORECASE)
# reasoning a thinking model inlines in its reply (servers that don't split it into its own field); an unclosed
# block is a reply cut off mid-thought
_THINK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.IGNORECASE | re.DOTALL)
_THINK_END = re.compile(r"</think(?:ing)?>", re.IGNORECASE)


def strip_thinking(text):
    """`text` without a thinking model's inline reasoning: each <think>...</think> block, an unclosed <think> to the
    end, and everything before a closing </think> whose opening tag was in the prompt (Qwen3's chat template). Its
    "So overall this should PASS" read as the verdict (2026-10-25 review)."""
    text = _THINK.sub("", text)
    ends = list(_THINK_END.finditer(text))
    return text[ends[-1].end():] if ends else text


def _unlabelled(line):
    """`line` with an echoed PASS/FAIL format label blanked out (same length, so positions in it hold)."""
    return _FORMAT_LABEL.sub(lambda m: " " * len(m.group()), line)
_SCORE = re.compile(r"\bscores?\b(?:\s*[(\[][^)\]\n]*[)\]])?[^\d\n]{0,8}?(-?\d+(?:[.,]\d+)?)\s*"
                    r"(?:(/|out\s+of)\s*(\d+(?:\.\d+)?)|(%))?", re.IGNORECASE)
# the scale a judge names before the value ('Score (0-1): 0.82', 'Score [1-10]: 8', 'Score (out of 5): 4'); it
# read as the value
_SCORE_RANGE = re.compile(r"[(\[]\s*(?:[01]\s*(?:[-–]|to)\s*|(?:out\s+)?of\s+)(\d+(?:\.\d+)?)\s*[)\]]",
                          re.IGNORECASE)
# a bare value on the line after a 'Score:' label ('**Score:**' with '0.85' below it)
_SCORE_VALUE = re.compile(r"^[\s*_`]*(-?\d+(?:[.,]\d+)?)\s*(?:(/|out\s+of)\s*(\d+(?:\.\d+)?)|(%))?[\s*_`.]*$",
                          re.IGNORECASE)
# NOT-MET / NOT MET / NOT_MET / **NOT** MET, and with typographic or full-width dashes
_DASH = r"[\s_*\-‐-―−－﹣]*"
# 'Partially MET', 'Barely met', 'not quite met', 'MET (partially)' are not MET: the rubric passes only what is
# clearly and fully satisfied. 'not only met' (but exceeded) is MET, and 'nothing' / 'note' are not 'not'.
_STATUS = re.compile(rf"(?<![A-Za-z])((?:not(?:(?![a-z])|(?=met)){_DASH}(?:(?!(?:only|just|merely|simply)\b)[a-z]+\s+)?"
                     rf"|(?:partially|partly|mostly|largely|nearly|almost|somewhat|half|semi|barely|hardly|scarcely"
                     rf"|marginally){_DASH})met|unmet|met\s*\(\s*(?:partially|partly|mostly|largely|barely)(?:\s+met)?"
                     rf"\s*\)|met)(?![A-Za-z])", re.IGNORECASE)
_COUNTED = re.compile(rf"(?<![\d./])[1-9]\d*\s*(?:criteria\s+|criterion\s+)?(?:not{_DASH}met|unmet)(?![A-Za-z])",
                      re.IGNORECASE)
# a count written label-first ('Met: 4  Not met: 0'): the number decides
_LABEL_COUNT = re.compile(rf"(?<![A-Za-z])(?:not{_DASH}met|unmet)\s*[:=]\s*(\d+)\s*(?:[,;|)]|$)", re.IGNORECASE)
_NOTHING_AFTER = re.compile(r"^[\W_]*(?:criteria|criterion|items?)?[\W_]*(?:none|nothing|n/?a|0|zero)\b"
                            r"[^A-Za-z0-9(]*(?:\(.*\))?[\W_]*$", re.IGNORECASE)
_ZERO_BEFORE = re.compile(r"(?<![\d.])0\s*(?:/\s*\d+\s*)?(?:criteria\s+|criterion\s+)?$", re.IGNORECASE)
# 'no NOT-MET criteria', 'none of them are unmet', 'nothing is unmet', 'for any NOT-MET criterion': a negation or
# a condition just before the word, with only words between (a ' - ' or ':' separator ends it), makes an
# unnumbered line a summary or an instruction. Not a numbered line: that is a criterion, whose label may read
# 'No missing or broken parts' or 'a knight without a helmet' (both were read as summaries, passing broken
# renders, 2026-10 review).
_NEGATED = re.compile(r"\b(?:no|none|nothing|zero|without|any|if)\b[\w\s']{0,30}$", re.IGNORECASE)
_NUMBERED = re.compile(r"^[\s*#>|_\-]*(?:criterion\s*)?\d+\s*[.):|]", re.IGNORECASE)
_MARKS = "❌✅✔✖✗✘"   # the check and cross marks judges put before a status
_CELL_TRIM = " \t*_`" + _MARKS


def _line_unmet(line):
    """True when a line of a judge's reply marks a criterion NOT-MET: a table cell holding only the status, a
    non-zero count ('1 NOT-MET'), or the line's first status word, NOT-MET (any spelling, 'partially met'
    included). Fail-safe: a numbered line is a criterion, so its status always counts. Only an unnumbered summary
    or instruction is let off: a negation just before the word ('No NOT-MET criteria', 'nothing is unmet', 'For
    any NOT-MET criterion ...'), nothing after it ('NOT MET: none'), a zero count ('0/3 NOT-MET', 'Not met: 0') or
    'unless'. Each of those failed correct renders, and the same escapes on a criterion ('1. NOT-MET: none (the top
    face is flat)') or a rule tight enough to require a label layout passed broken ones (2026-10 reviews)."""
    if "|" in line:
        cells = [c for c in (c.strip(_CELL_TRIM) for c in line.split("|")) if _STATUS.fullmatch(c)]
        if cells:
            return cells[0].lower() != "met"
    numbered = bool(_NUMBERED.match(line))
    lc = None if numbered else _LABEL_COUNT.search(line)
    if lc:
        return int(lc.group(1)) > 0
    if _COUNTED.search(line):
        return True
    m = _STATUS.search(line)
    if not m or m.group(1).lower() == "met":
        return False
    if numbered:
        return True
    before, after = line[:m.start()], line[m.end():]
    if _NOTHING_AFTER.match(after) or re.match(r"\s+unless\b", after, re.IGNORECASE) or _ZERO_BEFORE.search(before):
        return False
    return not _NEGATED.search(before)
# Also carry any line bearing a 'FIX:' directive (the judge's structured add/avoid correction) so
# the expander receives it even if the model puts it on its own line rather than the NOT-MET line.
_FIXLINE = re.compile(r"\bfix\b\s*[:\-]", re.IGNORECASE)
# A line that IS the overall-verdict / score line (allowing markdown bullets/emphasis), as opposed
# to a criterion reason that merely mentions 'overall'/'scored' mid-sentence.
_OVERALL_LINE = re.compile(r"\s*[*#>\-\s]*overall\b", re.IGNORECASE)
_SCORE_LINE = re.compile(r"\s*[*#>\-\s]*(?:final\s+)?scores?\b", re.IGNORECASE)
# a verdict label just before the PASS/FAIL ('NOT-MET: none. Overall: PASS', 'so the verdict is FAIL')
_VERDICT_AT = re.compile(r"\b(?:overall|verdict|result|final)\b[^:\n]{0,20}[:\-–—=]?\s*[*_]*\s*$", re.IGNORECASE)
# the rubric's own instructions echoed back (rubric.as_prompt): not a verdict, a criterion or a FIX. Its
# '<comma-separated visual elements to include>' reached the next prompt as a term to add.
_ECHO = re.compile(r"comma-separated (?:visual elements|traits)|PASS only if EVERY criterion|append on the SAME "
                   r"line a concrete fix|for each numbered criterion, state|Be strict: mark a criterion", re.IGNORECASE)


def parse_verdict(text: str) -> Verdict:
    """Parse a VLM judgment into a Verdict. Never raises."""
    try:
        if not text or not str(text).strip():
            return Verdict(passed=False, score=0.0, issues=[])
        lines = [l for l in strip_thinking(str(text)).splitlines() if not _ECHO.search(l)]

        # Decide PASS/FAIL from the verdict-bearing line only, so criterion
        # reasons containing the word 'fail' (or 'pass') don't contaminate the
        # overall verdict. The rubric puts the verdict at the END on its own line, so scan in
        # reverse and prefer a line STARTING with 'overall' — a criterion reason like
        # 'MET - overall composition passed' earlier in the text must never hijack the verdict.
        def _has_token(l):
            # a line whose status word comes before its PASS/FAIL is a criterion ('2. NOT-MET: the overall look
            # would not pass'), never the verdict: numbered, or marking a criterion NOT-MET unless a verdict label
            # introduces the token ('NOT-MET: none. Overall: PASS'). That criterion, taken as the verdict, was also
            # left out of the criterion check, so a judge's bare FAIL became a PASS (2026-10 review).
            v = _unlabelled(l)
            t = min((m.start() for m in (_PASS.search(v), _FAIL.search(v)) if m), default=None)
            s = _STATUS.search(l)
            return t is not None and (s is None or t < s.start() or not (
                _NUMBERED.match(l) or (_line_unmet(l) and not _VERDICT_AT.search(l[:t]))))
        verdict_line = next(
            (l for l in reversed(lines) if _OVERALL_LINE.match(l) and _has_token(l)), None)
        if verdict_line is None:
            verdict_line = next(
                (l for l in reversed(lines) if "overall" in l.lower() and _has_token(l)), None)
        if verdict_line is None:
            verdict_line = next((l for l in reversed(lines) if _has_token(l)), "")
        # FAIL takes precedence; PASS only on an explicit standalone token. The rubric says PASS only if
        # every criterion is MET, so a criterion marked NOT-MET also fails it: a small judge wrote "NOT-MET:
        # the head is completely absent" and then "Overall: PASS" (2026-10 judge benchmark).
        failed = bool(_FAIL.search(_unlabelled(verdict_line)))
        criterion_unmet = any(_line_unmet(l) for l in lines if l.strip() != verdict_line.strip())
        # ... and so does the verdict line's own confession after the PASS ('PASS - criterion 2 is partially met'),
        # or before its label: left out of the criterion check above, 'Summary: criterion 2 is NOT-MET (orange body).
        # Overall: PASS' passed (2026-10-25 review). 'NOT-MET: none. Overall: PASS' still does.
        pm = _PASS.search(_unlabelled(verdict_line))
        before = verdict_line[:pm.start()] if pm else ""
        label = _VERDICT_AT.search(before)
        verdict_unmet = bool(pm) and (_line_unmet(verdict_line[pm.end():])
                                      or _line_unmet(before[:label.start()] if label else before))
        passed = bool(pm) and not failed and not criterion_unmet and not verdict_unmet

        # Score: prefer the dedicated trailing 'score: ...' line (rubric instruction); fall back
        # to the LAST match anywhere, so prose like 'scored 7 criteria' can't clamp to 1.0.
        m = None
        for i in range(len(lines) - 1, -1, -1):
            if _SCORE_LINE.match(lines[i]):
                m = _SCORE.search(lines[i])
                nxt = next((l for l in lines[i + 1:] if l.strip()), None)
                if m is None and nxt is not None:   # the value on the line below the label
                    m = _SCORE_VALUE.match(nxt)
                if m:
                    break
        if m is None:
            all_scores = list(_SCORE.finditer("\n".join(lines)))
            m = all_scores[-1] if all_scores else None
        if m:
            val = float(m.group(1).replace(",", "."))     # 'score: 0,85'
            rng = _SCORE_RANGE.search(m.string, m.start(), m.start(1)) if m.re is _SCORE else None
            if m.group(3):                                  # "value/denom", "value out of denom"
                d = float(m.group(3)); val = val / d if d else 0.0
            elif m.group(4):                                # "value%"
                val = val / 100.0
            elif rng:                                       # "Score (0-10): 8"
                d = float(rng.group(1)); val = val / d if d else 0.0
            elif val >= 2:                                  # 'score: 7' on a 0-10 scale, 'score: 85' on 0-100
                val = val / 10 if val <= 10 else val / 100  # (both used to read as a perfect 1.0); 1.7 clamps
            score = max(0.0, min(1.0, val))
        else:
            score = 0.0

        issues = []
        vseg = verdict_line.strip()
        for line in lines:
            seg = line.strip()
            # Collect genuine NOT-MET lines (and any standalone FIX: directive line); skip only
            # the verdict line ITSELF — a NOT-MET reason may legitimately say 'overall proportions'
            # and its FIX feedback must still reach the expander — unless it confesses an unmet criterion.
            if seg and (verdict_unmet if seg == vseg else (_line_unmet(seg) or _FIXLINE.search(seg))):
                issues.append(seg)

        return Verdict(passed=passed, score=score, issues=issues)
    except Exception as e:
        print(f"[agent] parse_verdict failed: {e}", file=sys.stderr)
        return Verdict(passed=False, score=0.0, issues=["unparseable verdict"])


_TEMPLATE = "agent-vlm-judge.json"


class LocalVLMJudge(Judge):
    """Judge an image with Qwen3-VL run as a ComfyUI graph (1038lab/ComfyUI-QwenVL) — the OPTIONAL
    judge path; the default/recommended judge is the Ollama LLMJudge (see scripts/agent/llm.py +
    auto_generate.py --backend api). Fills agent-vlm-judge.json (uploaded image + rubric.as_prompt()),
    queues it, reads the verdict text the graph wrote via SaveImageTextDataSetToFolder, and parses it."""

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


def combine_verdicts(verdicts, *, pass_threshold=None) -> Verdict:
    """Aggregate N independent verdicts into one by majority vote:
      passed = at least `pass_threshold` passed (strict majority by default),
      score  = mean of the sub-scores,
      issues = order-preserving, de-duplicated union of every verdict's issues (so the expander
               addresses every raised concern on the next iteration).
    The shared core of both the Judge panel (ConsensusJudge) and the free-text panel
    (consensus_verdict). Raises ValueError on an empty list."""
    verdicts = list(verdicts)
    if not verdicts:
        raise ValueError("need at least one verdict to combine")
    # strict majority: more than half must pass (N=2 -> unanimous; N=3 -> 2; N=5 -> 3)
    threshold = pass_threshold if pass_threshold is not None else (len(verdicts) // 2) + 1
    passes = sum(1 for v in verdicts if v.passed)
    score = sum(v.score for v in verdicts) / len(verdicts)
    seen, issues = set(), []
    for v in verdicts:
        for it in v.issues:
            if it not in seen:
                seen.add(it); issues.append(it)
    return Verdict(passed=passes >= threshold, score=round(score, 4), issues=issues)


def consensus_verdict(texts, *, pass_threshold=None) -> Verdict:
    """Combine the assistant's M independent free-text vision passes into one consensus Verdict:
    parse each with parse_verdict, then majority-vote via combine_verdicts. This is the assistant
    consensus judge's core primitive — used when the agent is in the loop and IS the judge (it has
    no headless VLM; the local backend's LocalVLMJudge is the autonomous path)."""
    return combine_verdicts([parse_verdict(t) for t in texts], pass_threshold=pass_threshold)


class CallableJudge(Judge):
    """Adapt a plain callable into a Judge: `fn(image_path, rubric)` returns either a free-text
    verdict (parsed via parse_verdict) or a ready Verdict. This is the seam the assistant uses to
    plug its own vision passes into ConsensusJudge / run_loop when the agent is driving the loop.
    There is deliberately no headless implementation — a bare subprocess has no assistant vision to
    call, which is exactly why the assistant backend is gated to agent-in-the-loop use."""

    def __init__(self, fn):
        self.fn = fn

    def judge(self, image_path, rubric) -> Verdict:
        out = self.fn(image_path, rubric)
        return out if isinstance(out, Verdict) else parse_verdict(out)


class ConsensusJudge(Judge):
    """A judge panel: aggregate N sub-judges into one Verdict by majority vote. Each sub-judge
    scores the image independently; the panel combines them via combine_verdicts (strict-majority
    PASS, mean score, de-duplicated union of issues). Judge-agnostic — the diversity comes from the
    judges you pass in (different VLMs, prompts, or an assistant panel of CallableJudges), all behind
    the same `Judge` seam. A sub-judge that raises counts as a fail and never crashes the panel, so
    one flaky judge can't take the loop down."""

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
        return combine_verdicts(verdicts, pass_threshold=self.pass_threshold)


class GeometryAwareJudge(Judge):
    """Wrap an inner judge and fold deterministic geometry facts into its verdict. After the inner
    judge scores the contact sheet, read the sibling '<stem>.checks.json' (written by the render
    generator from mesh_eval's bmesh probe); on any structural failure force passed=False and union
    the structural NOT-MET lines in. A VLM can't see watertightness/holes/disconnected chunks from a
    render — this is how those get caught. No checks file (or a corrupt one) → pure passthrough.
    `strict` (the CAD loop) demands one solid by raw island count; see geometry.structural_issues."""

    def __init__(self, inner: Judge, *, checks_suffix=RENDER_CHECKS_SUFFIX, strict=False):
        self.inner = inner
        self.checks_suffix = checks_suffix
        self.strict = strict

    def judge(self, image_path, rubric) -> Verdict:
        v = self.inner.judge(image_path, rubric)
        p = Path(image_path)
        cf = p.with_name(p.stem + self.checks_suffix)
        if not cf.exists():
            return v
        try:
            checks = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            return v
        extra = structural_issues(checks, strict=self.strict)
        if not extra:
            return v
        seen, issues = set(), []
        for it in list(v.issues) + extra:
            if it not in seen:
                seen.add(it)
                issues.append(it)
        # the VLM's score stays as it judged the look; geometry_failed ranks it below every clean candidate
        return Verdict(passed=False, score=v.score, issues=issues, geometry_failed=True)
