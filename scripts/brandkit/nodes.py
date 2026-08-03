"""Shared ComfyUI-graph utilities for the fillers: address nodes by a stable _meta.title
instead of raw numeric id (re-saving a graph in ComfyUI renumbers ids; titles are stable, so
fillers locate slots by title and fail loudly if a template drops one), load the tracked
templates, and guard the splice injectors' reserved node ids."""
from __future__ import annotations
import json
from pathlib import Path


class NodeNotFound(KeyError):
    pass


def find_node_by_title(wf: dict, title: str):
    """Return (node_id, node) for the node whose _meta.title == title. Raises NodeNotFound."""
    for nid, node in wf.items():
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == title:
            return nid, node
    raise NodeNotFound(f"no node titled {title!r} in workflow (template missing its stable title?)")


def node(wf: dict, title: str):
    """The node dict for a stable title — find_node_by_title without the id. The shared `_n`
    every filler used to redefine locally."""
    return find_node_by_title(wf, title)[1]


def load_template(repo_root, name: str) -> dict:
    """Parse a tracked workflow template by filename. Each call is a fresh parse, so callers
    may mutate the result freely (no deepcopy needed)."""
    p = Path(repo_root) / "workflows" / "templates" / name
    return json.loads(p.read_text(encoding="utf-8"))


def assert_free_ids(wf: dict, *ids: str):
    """Guard for the graph-splice injectors, which write FIXED reserved node ids (70-99): a
    template already using one would silently lose its node to dict assignment — raise instead."""
    used = [i for i in ids if i in wf]
    if used:
        raise ValueError(f"template already uses reserved node id(s) {', '.join(used)} — "
                         "splice injectors reserve ids 70-99; renumber the template")
