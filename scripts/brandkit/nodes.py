"""Address ComfyUI graph nodes by a stable _meta.title instead of raw numeric id.
Re-saving a graph in ComfyUI renumbers node ids; titles are stable, so fillers and the
watermark injector locate slots by title and fail loudly if a template drops one."""
from __future__ import annotations


class NodeNotFound(KeyError):
    pass


def find_node_by_title(wf: dict, title: str):
    """Return (node_id, node) for the node whose _meta.title == title. Raises NodeNotFound."""
    for nid, node in wf.items():
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == title:
            return nid, node
    raise NodeNotFound(f"no node titled {title!r} in workflow (template missing its stable title?)")
