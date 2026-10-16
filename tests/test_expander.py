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


def test_correction_brandless_has_no_empty_brand_lead():
    # brandless (no style/palette): the correction must NOT emit a malformed
    # "render strictly in the  style, using only the brand palette ()" — it degrades to a bare
    # "Correct the previous attempt." + the add-emphasis. This is the unbranded judge+correction path.
    e = TemplatedExpander()
    issues = ["1. NOT-MET. FIX: add a serpent-headed tail; avoid plain lion tail"]
    pos, neg = e.expand("a chimera with a serpent tail", BrandManifest(name="Bare"),
                        prior_issues=issues)
    assert pos.lower().startswith("correct the previous attempt")
    assert "strictly in the" not in pos.lower()      # no brand-style anchor
    assert "brand palette" not in pos.lower()         # no palette anchor
    assert "serpent-headed tail" in pos               # the add term is still emphasized
    assert "plain lion tail" in neg                   # avoid term still augments the negative


def test_strip_terms_respects_word_boundaries():
    # an avoid term that is a SUBSTRING of a subject word must leave the word intact
    from scripts.agent.expander import _strip_terms
    assert _strip_terms("a toyota land rover, rugged", ["toy"]) == "a toyota land rover, rugged"


def test_strip_terms_removes_avoid_and_tidies():
    from scripts.agent.expander import _strip_terms
    out = _strip_terms("a glossy plastic toy rover, candy colors, six wheels",
                       ["toy", "glossy plastic", "candy colors"])
    assert "toy" not in out.lower() and "candy" not in out.lower() and "glossy plastic" not in out.lower()
    assert "rover" in out and "six wheels" in out          # on-brand parts preserved
    assert ", ," not in out                                # tidy: no doubled commas


def test_correction_resolves_contradictory_fixes_in_the_brands_favour():
    # Live 2026-10 (Qwen3-VL-8B, 3 consensus passes) on an off-brand subject: the passes disagreed and one
    # asked to avoid the brand's own style; applying both sides inverted the correction. The brand wins.
    e = TemplatedExpander()
    issues = [
        "2. NOT-MET: cartoonish. FIX: add smooth rounded cartoonish styling; avoid rugged tactical, #1c1f22",
        "3. NOT-MET: palette missing. FIX: add candy-red bodywork, #c8442e; avoid candy-red",
        "5. NOT-MET: toy-like. FIX: add matte armor plating; avoid glossy plastic",
    ]
    pos, neg = e.expand("a glossy plastic rover with candy-red bodywork", _m(), prior_issues=issues)
    ensure = pos.split("Ensure these are present:")[1]
    assert "cartoonish" not in ensure and "candy" not in ensure       # clash with brand negative / an avoid
    assert "matte armor plating" in ensure and "#c8442e" in ensure     # brand-consistent adds survive
    assert "candy" not in pos.lower() and "glossy plastic" not in pos.lower()   # stripped from the subject
    assert "candy-red" in neg and "glossy plastic" in neg
    assert "rugged tactical" not in neg and "#1c1f22" not in neg       # never avoid the brand's own traits


def test_add_none_is_not_a_term_and_a_structured_fix_never_falls_back_to_raw_issues():
    e = TemplatedExpander()
    pos, neg = e.expand("rover", _m(), prior_issues=["5. NOT-MET: toy-like. FIX: add none; avoid toy-like"])
    assert "ensure these are present" not in pos.lower()
    assert "toy-like" in neg and "fix:" not in pos.lower()
    # every term filtered by the guard: still no raw (contradictory) issue text in the prompt
    pos, _ = e.expand("rover", _m(), prior_issues=["2. NOT-MET. FIX: add cartoonish look; avoid rugged tactical"])
    assert "cartoonish look" not in pos and "fix:" not in pos.lower()
    assert pos.lower().startswith("correct the previous attempt")


def test_parse_fixes_reads_what_small_judges_actually_write():
    from scripts.agent.expander import parse_fixes
    # either order, 'remove' for avoid, 'and' lists (live Qwen3-VL-8B phrasings, 2026-10)
    assert parse_fixes(["FIX: avoid cartoonish, toy-like; add rugged armor"]) == (["rugged armor"], ["cartoonish", "toy-like"])
    assert parse_fixes(["FIX: remove candy-red and sunny-yellow; add matte black"]) == (["matte black"], ["candy-red", "sunny-yellow"])
    # 'none needed' and a mid-clause verb switch: the skipped terms never become additions
    assert parse_fixes(["FIX: none needed."]) == ([], [])
    assert parse_fixes(["FIX: none needed, change the palette to pastel shades, add rugged armor, hard edges"]) == (
        ["rugged armor", "hard edges"], [])
    # no cap across consensus passes at 10 terms: a later pass's avoid list still arrives
    many = [f"FIX: add a{i}, b{i}, c{i}; avoid x{i}" for i in range(6)]
    add, avoid = parse_fixes(many)
    assert len(add) == 18 and avoid == [f"x{i}" for i in range(6)]


def test_correct_subject_drops_flagged_styling_but_keeps_the_object():
    from scripts.agent.expander import correct_subject
    s = "a six-wheeled rover, bright candy-red plastic bodywork, cheerful kids' toy, pastel colors, knobby tires"
    assert correct_subject(s, ["candy-red", "toy", "pastel colors"]) == "a six-wheeled rover, knobby tires"
    assert correct_subject("a glossy candy-red toy rover", ["glossy", "candy-red", "toy"]) == "a rover"
    assert correct_subject("a rover", ["rover"]) == "a rover"          # never strips the object away



def test_an_avoid_phrase_with_and_inside_it_stays_whole():
    # split at ' and ', 'avoid gaps between blades and hub' cut 'hub' out of '... with a central hub'
    from scripts.agent.expander import parse_fixes
    assert parse_fixes(["2. Form: NOT-MET FIX: add solid hub connection; avoid gaps between blades and hub"]) == (
        ["solid hub connection"], ["gaps between blades and hub"])
    assert parse_fixes(["FIX: add a central hub and avoid floating blades"]) == (["central hub"], ["floating blades"])
    assert parse_fixes(["FIX: avoid wings and horns"]) == ([], ["wings", "horns"])


def test_brand_guard_keeps_palette_colors_avoided_by_their_rubric_names():
    # the rubric names #1c1f22 'near-black' for the judge, so that is how the judge asks to avoid it
    from scripts.agent.expander import brand_guard
    add, avoid = brand_guard([], ["near-black", "red", "candy-red", "glossy plastic"], _m())
    assert avoid == ["candy-red", "glossy plastic"]


def test_the_templated_expander_never_cuts_the_objects_noun():
    pos, neg = TemplatedExpander().expand("a 12-blade fan rotor with a central hub", _m(),
                                          ["1. Form: NOT-MET FIX: avoid hub"])
    assert "central hub" in pos and "hub" in neg
