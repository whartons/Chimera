from __future__ import annotations
import pytest
from scripts.brandkit.manifest import BrandManifest
from scripts.agent.expander import PromptExpander, TemplatedExpander


def _m() -> BrandManifest:
    return BrandManifest(
        name="ACME",
        style="rugged tactical",
        palette=["#1c1f22", "#c8442e"],
        negative="blurry, cartoonish",
    )


def test_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        PromptExpander()  # abstract


def test_templated_expand_injects_subject_and_brand_style():
    e = TemplatedExpander()
    pos, neg = e.expand("rover", _m())
    assert "rover" in pos                       # subject
    assert "rugged tactical" in pos             # brand style injected by build_prompt
    assert neg == "blurry, cartoonish"          # brand negative


def test_correction_applies_judge_fix_add_emphasis_avoid_negative_and_strips_subject():
    e = TemplatedExpander()
    issues = ["1. NOT-MET - looks like a toy. FIX: add rugged armor plating, matte tactical finish; "
              "avoid toy, glossy plastic, candy colors"]
    pos, neg = e.expand("a glossy plastic toy rover", _m(), prior_issues=issues)
    # leads with a forceful brand re-assertion
    assert pos.lower().startswith("correct the previous attempt")
    assert "strictly in the rugged tactical style" in pos and "#1c1f22" in pos
    # the judge's ADD terms are emphasized in the positive
    assert "rugged armor plating" in pos and "matte tactical finish" in pos
    # the off-brand AVOID terms are STRIPPED from the positive (Z-Image ignores the negative) ...
    assert "toy" not in pos.lower() and "glossy plastic" not in pos.lower() and "candy" not in pos.lower()
    # ... and appended to the negative (for models that honor it, e.g. FLUX.2)
    assert "toy" in neg and "glossy plastic" in neg and "candy colors" in neg


def test_correction_falls_back_to_brand_lead_plus_raw_issues_when_no_fix():
    e = TemplatedExpander()
    pos, neg = e.expand("rover", _m(), prior_issues=["palette washed out", "too soft"])
    assert pos.lower().startswith("correct the previous attempt")
    assert "strictly in the rugged tactical style" in pos
    assert "fix: palette washed out; too soft" in pos.lower()
    assert neg == "blurry, cartoonish"          # no avoid terms -> negative unchanged


def test_templated_expand_empty_prior_issues_no_correction_clause():
    e = TemplatedExpander()
    pos, _ = e.expand("rover", _m(), prior_issues=[])
    assert "correct the previous attempt" not in pos.lower()
    assert "fix:" not in pos.lower()


def test_parse_fixes_extracts_add_and_avoid_deduped():
    from scripts.agent.expander import parse_fixes
    add, avoid = parse_fixes([
        "x. NOT-MET. FIX: add front winch, roof mast; avoid bright orange, toy",
        "y. NOT-MET. FIX: add front winch; avoid toy",     # winch + toy are duplicates
    ])
    assert add == ["front winch", "roof mast"]
    assert avoid == ["bright orange", "toy"]


def test_parse_fixes_none_when_absent():
    from scripts.agent.expander import parse_fixes
    assert parse_fixes(["no directive here", "palette absent"]) == ([], [])


def test_strip_terms_removes_avoid_and_tidies():
    from scripts.agent.expander import _strip_terms
    out = _strip_terms("a glossy plastic toy rover, candy colors, six wheels",
                       ["toy", "glossy plastic", "candy colors"])
    assert "toy" not in out.lower() and "candy" not in out.lower() and "glossy plastic" not in out.lower()
    assert "rover" in out and "six wheels" in out          # on-brand parts preserved
    assert ", ," not in out                                # tidy: no doubled commas
