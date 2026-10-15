"""Expand a subject into a brand-aware (positive, negative) prompt pair.

The expander is the refinement hinge. On a correction pass it doesn't just restate the judge's
complaint — it acts on the judge's STRUCTURED guidance: each NOT-MET criterion carries a
'FIX: add <...>; avoid <...>' directive (see rubric.as_prompt), and the expander turns that into a
real prompt change:

  - `add` terms  -> emphasized in the POSITIVE ("Ensure these are present: ..."),
  - `avoid` terms -> STRIPPED out of the subject in the positive AND appended to the negative.

The positive matters most because Z-Image (the default judge-loop model) zeroes the text negative —
so removing the off-brand terms from the positive is what actually changes the render. The negative
augmentation still helps models that honor it (e.g. FLUX.2). If the judge emitted no FIX directive,
we fall back to leading with a forceful brand re-assertion + the raw issues."""
from __future__ import annotations
import re
from abc import ABC, abstractmethod

from scripts.brandkit.prompt import build_prompt

_FIX = re.compile(r"\bfix\b\s*[:\-]\s*(.+)", re.IGNORECASE)


_EMPTY = {"none", "n/a", "na", "nothing", "-"}   # 'FIX: add none; avoid …' (a judge with nothing to add)


def _dedup(terms, cap=10, maxlen=60):
    """Split a chunk into clean, de-duplicated, length-capped terms (comma/semicolon separated)."""
    out, seen = [], set()
    for raw in re.split(r"[;,]", terms or ""):
        t = raw.strip().strip(".").strip()
        if t and t.lower() not in _EMPTY and len(t) <= maxlen and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= cap:
            break
    return out


def _word(term):
    """A whole-word pattern for `term`. Lookarounds, not \\b: \\b never matches before '#', so brand
    palette hex codes (#1c1f22) went unmatched; 'toy' must still not match inside 'toyota'."""
    return r"(?<!\w)" + re.escape(term) + r"(?!\w)"


def _overlaps(term, others):
    """True when `term` and one of `others` contain each other as whole words (case-insensitive)."""
    t = term.lower()
    return any(o and (re.search(_word(o), t) or re.search(_word(t), o)) for o in others)


def brand_guard(add, avoid, manifest):
    """Resolve contradictory FIX terms in the brand's favour. Consensus passes (and small judges) can
    disagree, e.g. one pass says 'add candy-red' while another says 'avoid candy-red', or a pass says
    'avoid matte black' for a matte-black brand; applying both sides inverted the correction (2026-10).
    Drops `avoid` terms that would strip the brand's own style or palette, then `add` terms that clash
    with a remaining `avoid` term or with the brand's negative traits."""
    brand_keep = [t.lower() for t in _dedup(manifest.style, cap=50)] + [str(c).lower() for c in (manifest.palette or [])]
    avoid = [t for t in avoid if not _overlaps(t, brand_keep)]
    clash = [t.lower() for t in _dedup(manifest.negative, cap=50)] + [t.lower() for t in avoid]
    return [t for t in add if not _overlaps(t, clash)], avoid


_AVOID_VERB = re.compile(r"^(?:avoid|remove|eliminate|drop|exclude|without)\b\s*[:\-]?\s*", re.IGNORECASE)
_ADD_VERB = re.compile(r"^(?:add|include|use|apply|ensure)\b\s*[:\-]?\s*", re.IGNORECASE)
_SKIP_VERB = re.compile(r"^(?:none|nothing|n/a|no change|change|make|keep)\b", re.IGNORECASE)


def parse_fixes(issues):
    """Extract (add, avoid) term lists from the judge's 'FIX: add X; avoid Y' directives carried in
    the issue lines. Tolerant of what small judges actually write (2026-10, Qwen3-VL-8B): either order
    ('avoid X; add Y'), 'remove X' for avoid, 'none needed', a verb switch mid-clause ('none needed,
    change …, add Y'), and 'X and Y' lists. Each comma-term takes the most recent verb; 'none'/'change …'
    terms are skipped. Returns ([], []) when there is no FIX. Never raises."""
    add, avoid = [], []
    for issue in (issues or []):
        m = _FIX.search(str(issue))
        if not m:
            continue
        for clause in m.group(1).split(";"):
            mode = "add"                                    # the documented format leads with add
            for raw in clause.split(","):
                t = re.sub(r"^(?:and|or)\s+", "", raw.strip().strip(".").strip(), flags=re.IGNORECASE)
                if _AVOID_VERB.match(t):
                    mode, t = "avoid", _AVOID_VERB.sub("", t)
                elif _ADD_VERB.match(t):
                    mode, t = "add", _ADD_VERB.sub("", t)
                elif _SKIP_VERB.match(t):
                    mode = "skip"
                if mode != "skip":
                    (avoid if mode == "avoid" else add).extend(re.split(r"\s+and\s+", t))
    return _dedup(", ".join(add), cap=24, maxlen=80), _dedup(", ".join(avoid), cap=24, maxlen=80)


def _strip_terms(subject, avoid):
    """Remove the off-brand `avoid` terms from the subject text (case-insensitive), then tidy up the
    resulting whitespace/commas. This is what removes 'toy/glossy plastic' from the positive prompt."""
    s = subject
    for t in avoid:
        # whole-word: 'toy' must not gut 'toyota'
        s = re.sub(_word(t), "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(,\s*)+", ", ", s)
    return s.strip(" ,")


def correct_subject(subject, avoid):
    """The subject with the judge's flagged (`avoid`) styling removed, for branded runs: trailing comma-
    phrases containing an avoid term are dropped whole, and avoid terms are cut from the first phrase
    (the object) only while at least two words of it remain. The loop rebuilds the rubric from this, so
    a small judge stops being asked to verify the off-brand styling it was told to remove."""
    head, *rest = [p.strip() for p in subject.split(",")]
    cut = _strip_terms(head, avoid)
    head = cut if len(cut.split()) >= 2 else head
    rest = [p for p in rest if p and not _overlaps(p, [a.lower() for a in avoid])]
    return ", ".join([head, *rest])


class PromptExpander(ABC):
    """Turns a subject + manifest (+ optional prior issues) into prompts."""

    @abstractmethod
    def expand(self, subject, manifest, prior_issues=None) -> tuple[str, str]:
        """Return (positive, negative)."""
        raise NotImplementedError


class TemplatedExpander(PromptExpander):
    """Brand-aware expander built on build_prompt; on a correction pass it applies the judge's
    structured FIX directives (see module docstring)."""

    def expand(self, subject, manifest, prior_issues=None) -> tuple[str, str]:
        if not prior_issues:
            return build_prompt(manifest, subject)

        raw_add, raw_avoid = parse_fixes(prior_issues)
        add, avoid = brand_guard(raw_add, raw_avoid, manifest)
        eff_subject = _strip_terms(subject, avoid) if avoid else subject
        pos, neg = build_prompt(manifest, eff_subject)

        # Lead with a forceful brand re-assertion so the brand dominates the (corrected) prompt.
        anchors = []
        if manifest.style:
            anchors.append(f"strictly in the {manifest.style.strip()} style")
        if manifest.palette:
            anchors.append("using only the brand palette ("
                           + ", ".join(str(c) for c in manifest.palette) + ")")
        lead = "Correct the previous attempt"
        if anchors:
            lead += " — render " + ", ".join(anchors)
        pos = f"{lead}. {pos}"

        if add:
            pos += ". Ensure these are present: " + ", ".join(add)
        if avoid:
            neg = ", ".join(t for t in (neg, *avoid) if t)
        if not raw_add and not raw_avoid:               # judge gave no structured FIX -> surface raw
            pos += ". Fix: " + "; ".join(str(i) for i in prior_issues)
        return pos, neg
