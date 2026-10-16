"""Expand a subject into a brand-aware (positive, negative) prompt pair.

The expander is the refinement hinge. On a correction pass it doesn't just restate the judge's
complaint — it acts on the judge's STRUCTURED guidance: each NOT-MET criterion carries a
'FIX: add <...>; avoid <...>' directive (see rubric.as_prompt), and the expander turns that into a
real prompt change:

  - `add` terms  -> emphasized in the POSITIVE ("Ensure these are present: ..."),
  - `avoid` terms -> STRIPPED out of the subject in the positive AND appended to the negative.

The positive matters most: the image models the loop renders with sample at CFG 1 (Qwen-Image-2.1,
Z-Image Turbo, guidance-distilled FLUX.2), which skips the negative, so removing the off-brand terms
from the positive is what actually changes the render. The negative augmentation only reaches a model
sampled above CFG 1. If the judge emitted no FIX directive, we fall back to leading with a forceful
brand re-assertion + the raw issues."""
from __future__ import annotations
import re
from abc import ABC, abstractmethod

from scripts.agent.rubric import color_words
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
    palette hex codes (#1c1f22) went unmatched. A hyphenated word is one word: 'toy' must not match inside
    'toyota' or 'toy-like' (cutting 'toy' out of 'a toy-like rover' left 'a -like rover')."""
    return r"(?<![\w-])" + re.escape(term) + r"(?![\w-])"


def _contains(text, terms):
    """True when one of `terms` occurs inside `text` as a whole word (case-insensitive)."""
    t = text.lower()
    return any(o and re.search(_word(o.lower()), t) for o in terms)


def _overlaps(term, others):
    """True when `term` and one of `others` contain each other as whole words (case-insensitive)."""
    return _contains(term, others) or any(o and _contains(o, [term]) for o in others)


def brand_guard(add, avoid, manifest):
    """Resolve contradictory FIX terms in the brand's favour. Consensus passes (and small judges) can
    disagree, e.g. one pass says 'add candy-red' while another says 'avoid candy-red', or a pass says
    'avoid matte black' for a matte-black brand; applying both sides inverted the correction (2026-10).
    Drops `avoid` terms that overlap the brand's own style or palette (either way round), then `add` terms
    that CONTAIN a remaining `avoid` term or a brand negative trait ('add handle' survives 'avoid plastic
    handle'). Brand phrases of any length count: a 60-char cap had let a long style phrase through. A palette
    color avoided by the name the rubric gave the judge ('avoid near-black' for #1c1f22) is dropped too."""
    whole = dict(cap=10**6, maxlen=10**6)
    palette = [str(c) for c in (manifest.palette or [])]
    brand_keep = [t.lower() for t in _dedup(manifest.style, **whole)] + [c.lower() for c in palette]
    palette_names = {color_words(c).split(" (")[0].lower() for c in palette}
    avoid = [t for t in avoid if not _overlaps(t, brand_keep) and t.lower() not in palette_names]
    clash = [t.lower() for t in _dedup(manifest.negative, **whole)] + [t.lower() for t in avoid]
    return [t for t in add if not _contains(t, clash)], avoid


_AVOID_VERB = re.compile(r"^(?:avoid|remove|eliminate|exclude|without|get rid of)\b\s*[:\-]?\s*", re.IGNORECASE)
_ADD_VERB = re.compile(r"^(?:add|include|use|apply|ensure)\b\s*[:\-]?\s*", re.IGNORECASE)
_SKIP_VERB = re.compile(r"^(?:none|nothing|n/a|no change|change|make|keep)\b", re.IGNORECASE)
_CLAUSE = re.compile(r";|\.(?:\s+|$)")                       # ';' or a sentence end ('2.5 mm' stays whole)
_JOIN = re.compile(r"\s+(and|or)\s+", re.IGNORECASE)
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _pieces(clause):
    """A clause's terms: split at commas, and at 'and' / 'or' between short items ('wings and horns') or
    before a verb ('add X and avoid Y'), but not inside a longer phrase: 'gaps between blades and hub' is one
    term (split, its 'hub' was cut from the subject, 2026-10 review)."""
    out = []
    for chunk in clause.split(","):
        parts = _JOIN.split(chunk)                          # [text, conj, text, conj, text, ...]
        texts = parts[0::2]
        if len(texts) == 1 or all(len(t.split()) <= 2 for t in texts):
            out.extend(texts)
            continue
        cur = texts[0]
        for conj, t in zip(parts[1::2], texts[1:], strict=True):
            if _AVOID_VERB.match(t.strip()) or _ADD_VERB.match(t.strip()):
                out.append(cur)
                cur = t
            else:
                cur = f"{cur} {conj} {t}"
        out.append(cur)
    return out


def parse_fixes(issues):
    """Extract (add, avoid) term lists from the judge's 'FIX: add X; avoid Y' directives carried in
    the issue lines. Tolerant of what small judges actually write (2026-10, Qwen3-VL-8B): either order
    ('avoid X; add Y'), sentences ('add X. avoid Y'), 'remove X', 'X and Y' lists, a verb mid-clause ('add
    X and avoid Y'), and 'none needed' / 'change the palette to …' (skipped). Every piece takes the most
    recent verb, carried across clauses ('avoid X; Y; Z' avoids all three). Returns ([], []) when there is
    no FIX. Never raises."""
    add, avoid = [], []
    for issue in (issues or []):
        m = _FIX.search(str(issue))
        if not m:
            continue
        mode = "add"                                        # the documented format leads with add
        for clause in _CLAUSE.split(m.group(1)):
            for raw in _pieces(clause):
                t = raw.strip().strip(".").strip()
                v = _AVOID_VERB.match(t)
                if v:
                    mode, t = "avoid", t[v.end():]
                else:
                    v = _ADD_VERB.match(t)
                    if v:
                        mode, t = "add", t[v.end():]
                if _SKIP_VERB.match(t):                     # also 'add none needed' once the verb is cut
                    mode = "skip"
                    continue
                t = _ARTICLE.sub("", t.strip())
                if t and mode != "skip":
                    (avoid if mode == "avoid" else add).append(t)
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
    phrases containing an avoid term are dropped whole; avoid terms are cut from the first phrase (the
    object) only when its noun, the phrase's last word, survives ('a knight helmet with a plume' minus
    'plume' would leave 'a knight helmet with a'). The loop rebuilds the rubric from this, so a small
    judge stops being asked to verify the off-brand styling it was told to remove."""
    head, *rest = [p.strip() for p in subject.split(",")]
    cut = _strip_terms(head, avoid)
    if len(cut.split()) >= 2 and head.split() and cut.split()[-1].lower() == head.split()[-1].lower():
        head = cut
    rest = [p for p in rest if p and not _contains(p, avoid)]
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
        # correct_subject keeps the object's noun: cutting 'hub' from '... rotor with a central hub' left
        # '... with a central'
        eff_subject = correct_subject(subject, avoid) if avoid else subject
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
