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
_AVOID = re.compile(r"\bavoid\b\s*[:\-]?\s*", re.IGNORECASE)
_ADD = re.compile(r"^\s*add\b\s*[:\-]?\s*", re.IGNORECASE)


def _dedup(terms, cap=10, maxlen=60):
    """Split a chunk into clean, de-duplicated, length-capped terms (comma/semicolon separated)."""
    out, seen = [], set()
    for raw in re.split(r"[;,]", terms or ""):
        t = raw.strip().strip(".").strip()
        if t and len(t) <= maxlen and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= cap:
            break
    return out


def parse_fixes(issues):
    """Extract (add, avoid) term lists from the judge's 'FIX: add X; avoid Y' directives carried in
    the issue lines. Tolerant of formatting variations; returns ([], []) when none. Never raises."""
    add_chunks, avoid_chunks = [], []
    for issue in (issues or []):
        m = _FIX.search(str(issue))
        if not m:
            continue
        seg = m.group(1)
        am = _AVOID.search(seg)
        add_part, avoid_part = (seg[:am.start()], seg[am.end():]) if am else (seg, "")
        add_chunks.append(_ADD.sub("", add_part))
        avoid_chunks.append(avoid_part)
    return _dedup(", ".join(add_chunks)), _dedup(", ".join(avoid_chunks))


def _strip_terms(subject, avoid):
    """Remove the off-brand `avoid` terms from the subject text (case-insensitive), then tidy up the
    resulting whitespace/commas. This is what removes 'toy/glossy plastic' from the positive prompt."""
    s = subject
    for t in avoid:
        s = re.sub(re.escape(t), "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(,\s*)+", ", ", s)
    return s.strip(" ,")


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

        add, avoid = parse_fixes(prior_issues)
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
        if not add and not avoid:                       # judge gave no structured FIX -> surface raw
            pos += ". Fix: " + "; ".join(str(i) for i in prior_issues)
        return pos, neg
