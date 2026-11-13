"""评论解析：从监听到的 GraphQL 原始响应里提取评论节点。

支持三种查询：
  CommentsListComponentsPaginationQuery      顶层评论（depth 0）
  Depth1CommentsListPaginationQuery          一级回复（depth 1）
  Depth2CommentsListPaginationQuery          二级回复（depth 2）
"""

import json
import time

FIELDS = ["comment_id", "parent_id", "depth", "author", "text",
          "time", "like_count", "reply_count"]


def _iter_nodes(obj, depth=0):
    """递归找出所有像评论节点的 dict（含 legacy_fbid + body）。"""
    if depth > 14:
        return
    if isinstance(obj, dict):
        if obj.get("legacy_fbid") and isinstance(obj.get("body"), dict):
            yield obj
        for v in obj.values():
            yield from _iter_nodes(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_nodes(v, depth + 1)


def _like_count(node):
    fb = node.get("feedback") or {}
    total = 0
    tr = fb.get("top_reactions") or {}
    for e in tr.get("edges") or []:
        total += e.get("reaction_count") or 0
    if not total:
        ri = fb.get("reaction_count")
        if isinstance(ri, dict):
            total = ri.get("count") or 0
    return total


def parse_comment_node(node):
    ct = node.get("created_time")
    try:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ct))) if ct else ""
    except Exception:
        ts = ""
    parent = node.get("comment_direct_parent") or {}
    parent_id = ""
    if isinstance(parent, dict):
        parent_id = str(parent.get("legacy_fbid") or "")
    return {
        "comment_id": str(node.get("legacy_fbid") or ""),
        "parent_id": parent_id,
        "depth": int(node.get("depth") or 0),
        "author": ((node.get("author") or {}).get("name") or ""),
        "text": ((node.get("body") or {}).get("text") or ""),
        "time": ts,
        "like_count": _like_count(node),
        "reply_count": 0,
    }


def parse_response(raw):
    """解析一份 JSONL 响应，返回评论列表（可能为空）。"""
    out = []
    for line in (raw or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        for node in _iter_nodes(obj.get("data") or obj):
            rec = parse_comment_node(node)
            if rec["comment_id"]:
                out.append(rec)
    return out
