from __future__ import annotations
from scripts.agent.auto_generate import _parse_seeds


def test_parse_seeds_comma_separated():
    assert _parse_seeds("7,8,9") == [7, 8, 9]


def test_parse_seeds_none_and_empty_are_none():
    # None / '' are falsy -> None, so the loop falls back to its deterministic seeds
    assert _parse_seeds(None) is None
    assert _parse_seeds("") is None


def test_parse_seeds_skips_blank_segments():
    # whitespace-only / empty segments are dropped, not parsed as ints
    assert _parse_seeds("7, ,8") == [7, 8]
    assert _parse_seeds(" 3 , 4 ") == [3, 4]
