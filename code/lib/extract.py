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

COMMENT_FIELDS = [
    "post_id", "comment_id", "parent_id", "depth",
    "author", "author_id", "author_url", "author_avatar", "author_gender",
    "text", "text_ranges", "time", "created_time",
    "like_count", "like_breakdown", "reactors_count",
    "reply_count", "attachments", "is_ai", "is_hidden", "is_disabled",
    "spam_mode", "group_id", "is_anonymous", "has_attached_story",
    "translated", "translation_available",
]
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
    """feed 节点 → 帖子记录（尽量保留 raw 里的全部可用信息）。"""
    story = find_first(node, "story") or {}
    msg = (find_first(node, "message") or {}).get("text") or ""
    actors = story.get("actors") or node.get("actors") or []
    author = {"name": "", "id": "", "url": ""}
    if actors and isinstance(actors[0], dict):
        a = actors[0]
        author = {"name": a.get("name") or "", "id": a.get("id") or "",
                  "url": a.get("url") or ""}

    # 点赞：总数 + 分类明细
    reactions = {"total": None, "breakdown": {}}
    rc = find_first(node, "reaction_count")
    if isinstance(rc, dict):
        reactions["total"] = rc.get("count")
    elif rc is not None:
        reactions["total"] = rc
    tr = find_first(node, "top_reactions") or {}
    for e in (tr.get("edges") or []):
        name = ((e.get("node") or {}).get("localized_name") or "").strip()
        cnt = e.get("reaction_count") or 0
        if name and cnt:
            reactions["breakdown"][name] = cnt

    circ = find_first(node, "comment_rendering_instance") or {}
    cmt = (circ.get("comments") or {}).get("total_count") if isinstance(circ, dict) else None
    share = find_first(node, "share_count")
    share = share.get("count") if isinstance(share, dict) else share

    # 附件：类型 / id / 图片直链
    media_list = []
    for a in (node.get("attachments") or story.get("attachments") or []):
        m = (a.get("media") or {})
        st = (a.get("styles") or {}).get("attachment") or {}
        mm = st.get("media") or m
        mtype = mm.get("__typename") or m.get("__typename") or ""
        if not mtype:
            continue
        img = ((mm.get("photo_image") or {}).get("uri")
               or (mm.get("viewer_image") or {}).get("uri") or "")
        media_list.append({
            "type": mtype,
            "id": mm.get("id") or m.get("id") or "",
            "url": mm.get("url") or "",
            "image": img,
        })

    has_img = int(any("Photo" in x["type"] or "Image" in x["type"] for x in media_list))
    has_vid = int(any("Video" in x["type"] for x in media_list))

    repost = bool(node.get("work_is_repost") or node.get("attached_story"))

    # 转发的原帖 / 分享内容
    shared = None
    att_story = node.get("attached_story") or {}
    if isinstance(att_story, dict) and att_story:
        s_actors = find_first(att_story, "actors") or []
        s_author = (s_actors[0].get("name") if s_actors else "") or ""
        s_msg = (find_first(att_story, "message") or {}).get("text") or ""
        s_media = []
        for a2 in (find_first(att_story, "attachments") or [])[:3]:
            m2 = (a2.get("media") or {})
            img = ((m2.get("photo_image") or {}).get("uri")
                   or (m2.get("viewer_image") or {}).get("uri") or "")
            if img:
                s_media.append(img)
        shared = {
            "url": att_story.get("permalink_url") or "",
            "author": s_author,
            "text": s_msg,
            "images": s_media,
        }

    return {
        "post_id": str(node.get("post_id")),
        "post_url": node.get("permalink_url") or "",
        "author": author["name"],
        "author_id": author["id"],
        "author_url": author["url"],
        "post_time": _ts(node.get("creation_time")),
        "creation_time": node.get("creation_time"),
        "text": msg,
        "reactions": reactions,
        "like_count": reactions["total"],
        "comment_count": cmt,
        "share_count": share,
        "attachments": media_list,
        "has_image": has_img,
        "has_video": has_vid,
        "is_repost": repost,
        "shared_post": shared,
        "story_id": story.get("id") or "",
        "story_url": story.get("wwwURL") or "",
        "target_group_id": ((story.get("target_group") or {}).get("id")
                            if isinstance(story.get("target_group"), dict) else ""),
        "matched_terms": node.get("matched_terms") or [],
        "is_sponsored": bool(node.get("sponsored_data")),
        "source": "feed_raw",
    }


def preview_comments(node):
    """feed 节点 → 预览评论（0-2 条，字段尽量全）。"""
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
        au = c.get("author") or {}
        atts = []
        for a in (c.get("attachments") or []):
            m = (a.get("media") or {})
            img = ((m.get("photo_image") or {}).get("uri")
                   or (m.get("viewer_image") or {}).get("uri") or "")
            if img:
                atts.append(img)
        out.append({
            "post_id": str(node.get("post_id")),
            "comment_id": cid,
            "parent_id": "",
            "depth": c.get("depth") or 0,
            "author": au.get("name") or "",
            "author_id": au.get("id") or "",
            "text": ((c.get("body") or {}).get("text") or ""),
            "time": _ts(c.get("created_time")),
            "like_count": like,
            "reply_count": fb.get("total_reply_count") or 0,
            "attachments": "|".join(atts),
            "is_ai": int(bool(c.get("is_self_disclosed_as_ai_generated"))),
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
