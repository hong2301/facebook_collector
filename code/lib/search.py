"""Facebook 搜索结果：构造带筛选条件的 URL，解析帖子节点。

筛选条件通过 URL 的 filters 参数（base64 编码的 JSON）传递：
  近期帖子      recent_posts
  你看过的帖子   interacted_posts
  发布日期      creation_time（年/月/日区间）
  帖子来源      author_me（仅自己）
  地点          需要界面点击，暂不支持
"""

import base64
import json
import urllib.parse

BASE = "https://www.facebook.com/search/{kind}"
PROFILE = "https://www.facebook.com/profile.php?id={uid}"


def _wrap(name, args):
    """Facebook 把每个筛选项存成「JSON 字符串套 JSON 字符串」。"""
    return json.dumps({"name": name, "args": args}, separators=(",", ":"))


def build_filters(recent=False, seen=False, year=None, month=None,
                  author_me=False):
    """构造 filters 的 base64 串；无筛选返回空串。"""
    f = {}
    if recent:
        f["recent_posts:0"] = _wrap("recent_posts", "")
    if seen:
        f["seen_posts:0"] = _wrap("interacted_posts", "")
    if author_me:
        f["rp_author:0"] = _wrap("author_me", "")
    if year:
        sm = f"{year}-{month or 1}"
        em = f"{year}-{month or 12}"
        args = json.dumps({
            "start_year": str(year), "start_month": sm,
            "end_year": str(year), "end_month": em,
            "start_day": f"{year}-{month or 1}-1",
            "end_day": f"{year}-{month or 12}-31",
        }, separators=(",", ":"))
        f["rp_creation_time:0"] = _wrap("creation_time", args)
    if not f:
        return ""
    raw = json.dumps(f, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(raw.encode()).decode()


def build_search_url(keyword, kind="top", recent=False, seen=False,
                     year=None, month=None, author_me=False):
    """拼出完整搜索 URL。

    kind: top（综合） / posts（帖子）
    """
    url = BASE.format(kind=kind) + "?q=" + urllib.parse.quote(keyword)
    flt = build_filters(recent=recent, seen=seen, year=year, month=month,
                        author_me=author_me)
    if flt:
        url += "&filters=" + urllib.parse.quote(flt, safe="")
    return url


def iter_search_nodes(tree):
    """从搜索响应树里取出帖子 story 节点。"""
    serp = (tree.get("serpResponse")
            or (tree.get("node") or {}).get("serpResponse") or {})
    for e in (serp.get("results") or {}).get("edges") or []:
        vm = ((e or {}).get("rendering_strategy") or {}).get("view_model") or {}
        story = _find(vm, "story")
        if isinstance(story, dict) and story.get("post_id"):
            yield story


def _find(o, key, depth=0):
    if depth > 10:
        return None
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = _find(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find(v, key, depth + 1)
            if r is not None:
                return r
    return None
