"""从已落盘的 feed 原始响应里提取帖子与预览评论（零请求）。

feed 响应的每个 edge 节点自带：
  - 帖子本体：正文 / 时间 / 点赞 / 评论总数 / 分享 / 附件
  - interesting_top_level_comments：1-2 条预览评论
"""

import csv
import glob
import json
import os
import re
import time

from .listener import parse_body_tree
from .logger import get_logger

log = get_logger("collector")

COMMENT_FIELDS = ["post_id", "comment_id", "parent_id", "depth", "author",
                  "text", "time", "like_count"]
INDEX_FIELDS = ["post_id", "post_time", "author", "like_count", "comment_count",
                "share_count", "has_image", "has_video", "text_len",
                "comment_collected", "post_url"]


def find_first(obj, key, depth=0):
    """在嵌套结构里递归找第一个名为 key 的值。"""
    if depth > 16:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_first(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_first(v, key, depth + 1)
            if r is not None:
                return r
    return None


def _ts(value):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))
    except Exception:
        return ""


def iter_nodes(raw_path):
    """遍历一个 raw 文件里的所有 feed 节点。"""
    with open(raw_path, encoding="utf-8") as f:
        tree = parse_body_tree(f.read().split("\n"))
    node_root = tree.get("node") or {}
    gf = node_root.get("group_feed")
    if not isinstance(gf, dict):
        return                      # 评论等非 feed 响应不参与整理
    for edge in gf.get("edges") or []:
        node = (edge or {}).get("node") or {}
        if node.get("post_id"):
            yield node


def post_record(node):
    """feed 节点 → 帖子记录。"""
    story = find_first(node, "story") or {}
    msg = (find_first(node, "message") or {}).get("text") or ""
    actors = story.get("actors") or node.get("actors") or []
    author = ""
    if actors and isinstance(actors[0], dict):
        author = actors[0].get("name") or ""

    like = find_first(node, "reaction_count")
    like = like.get("count") if isinstance(like, dict) else like
    circ = find_first(node, "comment_rendering_instance") or {}
    cmt = (circ.get("comments") or {}).get("total_count") if isinstance(circ, dict) else None
    share = find_first(node, "share_count")
    share = share.get("count") if isinstance(share, dict) else share

    media = node.get("attachments") or story.get("attachments") or []
    has_img = has_vid = 0
    for a in media:
        t = str((a.get("media") or {}).get("__typename") or "")
        if "Image" in t or "Photo" in t:
            has_img = 1
        if "Video" in t:
            has_vid = 1

    return {
        "post_id": str(node.get("post_id")),
        "post_url": node.get("permalink_url") or "",
        "author": author,
        "post_time": _ts(node.get("creation_time")),
        "text": msg,
        "like_count": like,
        "comment_count": cmt,
        "share_count": share,
        "has_image": has_img,
        "has_video": has_vid,
        "source": "feed_raw",
    }


def preview_comments(node):
    """feed 节点 → 预览评论列表（0-2 条）。"""
    out = []
    for it in find_first(node, "interesting_top_level_comments") or []:
        c = (it or {}).get("comment") or {}
        cid = str(c.get("legacy_fbid") or "")
        if not cid:
            continue
        fb = c.get("feedback") or {}
        like = 0
        for e in ((fb.get("top_reactions") or {}).get("edges") or []):
            like += e.get("reaction_count") or 0
        out.append({
            "post_id": str(node.get("post_id")),
            "comment_id": cid,
            "parent_id": "",
            "depth": c.get("depth") or 0,
            "author": ((c.get("author") or {}).get("name") or ""),
            "text": ((c.get("body") or {}).get("text") or ""),
            "time": _ts(c.get("created_time")),
            "like_count": like,
        })
    return out


def write_output(posts_dir, comments_dir, posts, comments):
    """写 <posts_dir>/<pid>.json 与 <comments_dir>/<pid>.csv（不写索引）。"""
    cmts_dir = comments_dir
    os.makedirs(posts_dir, exist_ok=True)
    os.makedirs(comments_dir, exist_ok=True)

    by_post = {}
    for c in comments:
        by_post.setdefault(c["post_id"], []).append(c)

    for rec in posts:
        pid = rec["post_id"]
        rows = by_post.get(pid, [])
        # 已有文件（含已采评论进度）作为底稿，raw 数据只覆盖非空项
        path = os.path.join(posts_dir, pid + ".json")
        old = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:
                old = {}
        doc = dict(old)
        doc.update({k: v for k, v in rec.items() if v not in (None, "", [])})
        doc["comment_collected"] = max(old.get("comment_collected") or 0, len(rows))
        doc.setdefault("comment_source", "feed_preview")
        doc["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        # 与已有评论合并，避免覆盖已采集的完整评论
        merged = {}
        cpath = os.path.join(cmts_dir, pid + ".csv")
        if os.path.exists(cpath):
            with open(cpath, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("comment_id"):
                        merged[r["comment_id"]] = r
        for c in rows:
            merged.setdefault(c["comment_id"], {k: c.get(k, "") for k in COMMENT_FIELDS})
        with open(cpath, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, COMMENT_FIELDS)
            w.writeheader()
            for c in merged.values():
                w.writerow({k: c.get(k, "") for k in COMMENT_FIELDS})
        doc["comment_collected"] = max(doc.get("comment_collected") or 0, len(merged))
    return len(posts), len(comments)
