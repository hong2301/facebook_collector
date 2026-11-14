"""评论解析：从监听到的 GraphQL 原始响应里提取评论节点。

支持三种查询：
  CommentsListComponentsPaginationQuery      顶层评论（depth 0）
  Depth1CommentsListPaginationQuery          一级回复（depth 1）
  Depth2CommentsListPaginationQuery          二级回复（depth 2）
"""

import json
import time

FIELDS = [
    "post_id", "comment_id", "parent_id", "depth",
    "author", "author_id", "author_url", "author_avatar", "author_gender",
    "text", "text_ranges", "time", "created_time",
    "like_count", "like_breakdown", "reactors_count",
    "reply_count", "attachments", "is_ai", "is_hidden", "is_disabled",
    "spam_mode", "group_id", "is_anonymous", "has_attached_story",
    "translated", "translation_available",
]


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
    """评论节点 → 记录（尽可能保留 raw 里的字段）。"""
    ct = node.get("created_time")
    try:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ct))) if ct else ""
    except Exception:
        ts = ""

    au = node.get("author") or {}
    avatar = ((au.get("profile_picture_depth_0") or {}).get("uri")
              or (au.get("profile_picture_depth_1") or {}).get("uri") or "")

    body = node.get("body") or {}
    ranges = body.get("ranges") or []

    parent = node.get("comment_direct_parent") or {}
    parent_id = str(parent.get("legacy_fbid") or "") if isinstance(parent, dict) else ""

    fb = node.get("feedback") or {}
    breakdown = {}
    like = 0
    for e in ((fb.get("top_reactions") or {}).get("edges") or []):
        name = ((e.get("node") or {}).get("localized_name") or "").strip()
        cnt = e.get("reaction_count") or 0
        if name and cnt:
            breakdown[name] = cnt
            like += cnt
    if not like and isinstance(fb.get("reaction_count"), (int, float)):
        like = int(fb["reaction_count"])
    reactors = fb.get("reactors") or {}

    reply_count = (fb.get("replies_connection") or {}).get("count") or 0

    atts = []
    for a in (node.get("attachments") or []):
        m = (a.get("media") or {})
        img = ((m.get("photo_image") or {}).get("uri")
               or (m.get("viewer_image") or {}).get("uri") or "")
        if img:
            atts.append(img)
    cover = node.get("comment_cover") or {}
    if isinstance(cover, dict):
        cimg = ((cover.get("photo_image") or {}).get("uri") or "")
        if cimg:
            atts.append(cimg)

    gci = node.get("group_comment_info") or {}

    return {
        "comment_id": str(node.get("legacy_fbid") or ""),
        "parent_id": parent_id,
        "depth": int(node.get("depth") or 0),
        "author": au.get("name") or "",
        "author_id": au.get("id") or "",
        "author_url": au.get("url") or "",
        "author_avatar": avatar,
        "author_gender": au.get("gender") or "",
        "text": body.get("text") or "",
        "text_ranges": "|".join(
            f"{r.get('offset')}:{r.get('length')}:{r.get('entity', {}).get('__typename', '')}"
            for r in ranges if isinstance(r, dict)),
        "time": ts,
        "created_time": ct or "",
        "like_count": like,
        "like_breakdown": "|".join(f"{k}:{v}" for k, v in breakdown.items()),
        "reactors_count": reactors.get("count_reduced") or "",
        "reply_count": reply_count,
        "attachments": "|".join(atts),
        "is_ai": int(bool(node.get("is_self_disclosed_as_ai_generated"))),
        "is_hidden": int(bool(node.get("is_hidden_by_viewer"))),
        "is_disabled": int(bool(node.get("is_disabled"))),
        "spam_mode": node.get("spam_display_mode") or "",
        "group_id": ((gci.get("group") or {}).get("id") if isinstance(gci, dict) else "") or "",
        "is_anonymous": int(bool(gci.get("is_author_anonymous"))) if isinstance(gci, dict) else 0,
        "has_attached_story": int(bool(node.get("attached_story"))),
        "translated": (((node.get("translated_body_for_target_dialect") or {})
                        .get("text")) or ""),
        "translation_available": int(bool(node.get("translation_available_for_viewer"))),
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
