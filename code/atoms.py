"""原子层：最小可执行单元，每个函数只做一件事。

| 原子能力        | 函数                                   |
|----------------|----------------------------------------|
| 打开/连接端口    | open_port(port)                        |
| 检测是否登录     | check_login()                          |
| 采集一个主页帖子  | collect_group_posts(url, output, ...)   |

组合功能见 code/features.py，实现细节见 code/lib/。
"""

import csv
import glob
import json
import os
import re
import time

from lib import session
from lib.auth import is_logged_in
from lib.browser import wait_doc
from lib.config import RAW_DIR, ROOT
from lib.listener import GraphQLRecorder, parse_body_tree
from lib.logger import get_logger
from lib.scroll import at_bottom, scroll_once
from lib import extract as extractlib
from lib.comments import parse_response
from lib.utils import pick_pause
from lib import post as postlib

log = get_logger("collector")

_recorder = None


def open_port(port=9227):
    """接管浏览器端口（未启动则按 profile 拉起，保留登录态）。"""
    br = session.open_port(port)
    log.info("端口已连接：%s", port)
    return br


def check_login():
    """只读 cookie 判断登录态，不导航页面。"""
    tab = session.pick_tab()
    ok, detail = is_logged_in(tab)
    if ok:
        log.info("登录检查通过")
    else:
        log.error("登录检查未通过：%s", detail)
    return ok


def collect_group_posts(url, output=RAW_DIR, since="2025-01-01",
                        step=1800, pause_min=1.0, pause_max=3.0,
                        max_idle=10, max_rounds=99999,
                        prune_every=4, keep_screens=8, reload=True):
    """【核心】采集一个小组主页：打开链接 → 监听 → 滚动 → 停止。

    监听全程常开，与滚动节奏无关，中途手动滚动也不会漏记录。
    滚动到监听数据里出现早于 since 的帖子时停止。

    Returns:
        dict：rounds / reason / captured / elapsed
    """
    global _recorder
    # 按群组 ID 锁定标签页，避免多群组并行时抢同一个 tab
    gid = ""
    m = re.search(r"/groups/(\d+)", url or "")
    if m:
        gid = m.group(1)
    tab = session.pick_tab(f"groups/{gid}") if gid else session.get_tab()
    if reload:
        tab.get(url)
        wait_doc(tab, 25)
    else:
        log.info("接续模式：沿用当前页面位置，不重新加载")

    tab.listen.start("graphql")
    _recorder = GraphQLRecorder(tab, output, group=url)
    _recorder.start()
    log.info("监听已启动 -> %s | %s", output, url)

    since_ts = int(time.mktime(time.strptime(since, "%Y-%m-%d")))
    rounds = idle = 0
    reason = "max_rounds"
    t0 = time.time()

    try:
        while rounds < max_rounds:
            rounds += 1
            scroll_once(step, pause_min, pause_max,
                        prune_every=prune_every, keep_screens=keep_screens)

            oldest = _oldest_seen()
            if oldest and oldest < since_ts:
                reason = "reached_since"
                break
            if at_bottom() and _idle_grew(rounds):
                idle += 1
                if idle >= max_idle:
                    reason = "no_new_content"
                    break
            else:
                idle = 0
    finally:
        captured = len(_recorder.records) if _recorder else 0
        if _recorder:
            _recorder.stop()
            _recorder = None
        try:
            tab.listen.stop()
        except Exception:
            pass
        log.info("监听已停止，本次捕获 %s 个响应", captured)

    info = {"rounds": rounds, "reason": reason, "captured": captured,
            "elapsed": round(time.time() - t0, 1)}
    log.info("采集结束：%s 轮，原因=%s，捕获=%s，耗时=%ss",
             info["rounds"], info["reason"], info["captured"], info["elapsed"])
    return info


def _oldest_seen():
    """监听结果中出现的最早发帖时间（unix 秒）。"""
    if not _recorder:
        return None
    stamps = [r.get("min_ts") for r in _recorder.records if r.get("min_ts")]
    return min(stamps) if stamps else None


_height = {"last": 0}


def _idle_grew(_round):
    """本轮高度是否增长，用于判断是否还有新内容。"""
    h = session.get_tab().run_js("return document.body.scrollHeight") or 0
    grew = h > _height["last"]
    _height["last"] = h
    return not grew


def collect_post(post_url, output=None, sort="all",
                 max_comments=0, pause_min=1.0, pause_max=3.0,
                 scroll_pause_min=1.0, scroll_pause_max=3.0,
                 max_idle=5, max_rounds=500, prune_keep=40):
    """【核心】采集一个帖子：帖子基本数据 + 完整评论。

    Args:
        post_url:     帖子链接
        output:       输出目录（raw 与解析结果都写这里）
        sort:         评论排序 most_relevant / newest / all（默认 all）
        max_comments: 评论数量上限，0 表示不限制
        pause_min/max: 点击展开后的随机等待（秒）
        scroll_pause_min/max: 每次滚动后的随机等待（秒）
        max_idle:     连续无新增评论的轮数上限
        max_rounds:   滚动轮数硬上限
        prune_keep:   保留最近的评论节点数，其余在确认无未展开回复后删除

    Returns:
        dict：post_id / comments / rounds / reason
    """
    global _recorder
    tab = session.get_tab()
    # 同 URL 再 get 不会触发请求，先离开
    if post_url.split("?")[0].rstrip("/") in (tab.url or ""):
        tab.get("https://www.facebook.com/")
        time.sleep(2)
    tab.get(post_url)
    wait_doc(tab, 30)
    time.sleep(6)
    from lib.config import COMMENTS_DIR, POSTS_DIR
    output = output or POSTS_DIR
    os.makedirs(output, exist_ok=True)
    os.makedirs(COMMENTS_DIR, exist_ok=True)

    # 分享短链（/share/p/xxxx）需要先跳转，用最终 URL 解析 post_id
    post_id = postlib.parse_post_id(tab.url) or postlib.parse_post_id(post_url)
    if not post_id:
        log.error("无法从链接解析 post_id：%s", post_url)
        return {"post_id": "", "comments": 0, "rounds": 0,
                "reason": "bad_url"}
    base = postlib.extract_post(post_id)

    conn = _recorder
    tab.listen.start("graphql")
    _recorder = GraphQLRecorder(tab, RAW_DIR, group=post_url, feed_only=False)
    _recorder.start()
    log.info("监听已启动 -> %s | 帖子 %s", output, post_id)

    postlib.set_sort(sort)

    rounds = idle = 0
    reason = "max_rounds"
    comments = {}
    try:
        while rounds < max_rounds:
            rounds += 1
            t0 = time.time()
            postlib.scroll_to_bottom()
            t_scroll = time.time() - t0

            pause = pick_pause(scroll_pause_min, scroll_pause_max)
            time.sleep(pause)

            t1 = time.time()
            clicked = postlib.expand_comments(limit=6, pause_min=pause_min,
                                              pause_max=pause_max)
            t_click = time.time() - t1

            t2 = time.time()
            postlib.prune_comments(prune_keep)
            t_prune = time.time() - t2

            t3 = time.time()
            before = len(comments)
            comments = _collect_parsed(_recorder)
            t_parse = time.time() - t3
            grew = len(comments) - before

            log.info("轮 %s | 评论 %s (+%s) | 滚动%.1fs 等待%.1fs 点击%.1fs"
                     "(点%s) 清理%.1fs 解析%.1fs",
                     rounds, len(comments), grew, t_scroll, pause,
                     t_click, clicked, t_prune, t_parse)

            idle = 0 if grew else idle + 1
            if max_comments and len(comments) >= max_comments:
                reason = "max_comments"
                break
            # 连续 max_idle 轮无新增评论 => 没有更多了
            if idle >= max_idle:
                reason = "no_new_content"
                break
    finally:
        captured = len(_recorder.records) if _recorder else 0
        if _recorder:
            _recorder.stop()
            _recorder = None
        try:
            tab.listen.stop()
        except Exception:
            pass
        log.info("监听已停止，捕获 %s 个响应", captured)

    postlib.save_result(output, post_id, post_url, base, comments)
    info = {"post_id": post_id, "comments": len(comments), "rounds": rounds,
            "reason": reason}
    log.info("帖子采集完成：%s", info)
    return info


def _collect_parsed(recorder):
    """把已捕获的响应解析成评论字典（按 comment_id 去重）。"""
    out = {}
    for rec in list(recorder.records):
        path = os.path.join(recorder.outdir, rec["file"])
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        for c in parse_response(raw):
            out[c["comment_id"]] = c
    return out


def raw_to_posts(raw_dir=RAW_DIR, posts_dir=None, comments_dir=None):
    """【原子】读取 feed 原始响应，输出帖子 JSON + 评论 CSV（零请求）。

    帖子写 <posts_dir>/<post_id>.json，评论写 <comments_dir>/<post_id>.csv。

    Returns:
        (帖子数, 评论数)
    """
    from lib.config import COMMENTS_DIR, POSTS_DIR
    posts_dir = posts_dir or POSTS_DIR
    comments_dir = comments_dir or COMMENTS_DIR
    posts, comments = {}, {}
    files = sorted(glob.glob(os.path.join(raw_dir, "*.jsonl")))
    if not files:
        log.warning("没有可提取的 raw 文件：%s", raw_dir)
        return 0, 0

    for path in files:
        for node in extractlib.iter_nodes(path):
            rec = extractlib.post_record(node)
            posts.setdefault(rec["post_id"], rec)
            for c in extractlib.preview_comments(node):
                comments.setdefault(c["comment_id"], c)

    return extractlib.write_output(posts_dir, comments_dir,
                                   list(posts.values()),
                                   list(comments.values()))


def translate_texts(texts, pause=1.2):
    """【原子】批量英译中（带缓存），返回 {原文: 译文}。"""
    from lib.translate import translate_texts as _t
    return _t(texts, pause=pause)


def translate_raw_fields(raw_dir=None, limit=0, pause=10, batch=20):
    """【原子】把 raw 里的正文翻译成中文，逐批写回 aiTranslateText。

    - 已有 aiTranslateText 的字段自动跳过
    - 每翻译成功一批就立刻写回 raw 并保存缓存，中断不丢进度

    Returns:
        (待译字段数, 唯一文本数, 写入数)
    """
    from lib.config import RAW_DIR
    from lib import rawtranslate as rt
    from lib.translate import _translate_batch, save_cache, _load_cache
    raw_dir = raw_dir or RAW_DIR

    jobs = rt.collect_jobs(raw_dir)
    if limit:
        jobs = jobs[:limit]
    uniq = list(dict.fromkeys(t for _, _, _, t in jobs))
    log.info("待翻译字段 %s 个 / 唯一文本 %s 条", len(jobs), len(uniq))
    if not uniq:
        return 0, 0, 0

    cache = _load_cache()
    written = 0
    for i in range(0, len(uniq), batch):
        chunk = uniq[i:i + batch]
        out = _translate_batch(chunk)
        if out is None:
            log.warning("第 %s 批失败，跳过（下次会补）", i // batch + 1)
            continue
        mapping = {src: dst for src, dst in zip(chunk, out) if dst}
        cache.update(mapping)
        sub = [j for j in jobs if j[3] in mapping]
        written += rt.write_back(sub, mapping)
        save_cache()
        log.info("已翻 %s/%s，累计写回 %s 个字段",
                 min(i + batch, len(uniq)), len(uniq), written)
        time.sleep(pause)
    return len(jobs), len(uniq), written


def collect_search_posts(url, output=None, since="2025-01-01",
                         step=1800, pause_min=1.0, pause_max=3.0,
                         max_idle=5, max_rounds=2000, prune_every=4,
                         keep_screens=8, reload=True):
    """【原子】按搜索链接采集帖子：滚动 + 监听，直到落到 since 之前。

    Args:
        url: 完整搜索链接（含 q 与 filters）
        output: 帖子输出目录（默认 data/posts）
        since: 停止日期，滚动到更早的帖子就停

    Returns:
        dict：rounds / captured / reason / posts
    """
    import time as _time
    from lib import search as searchlib
    from lib.config import POSTS_DIR
    from lib.extract import post_record

    global _recorder
    output = output or POSTS_DIR
    os.makedirs(output, exist_ok=True)

    tab = session.pick_tab("search")
    log.info("搜索采集：%s", url[:100])

    # 先开监听再加载页面，否则首屏的搜索响应会漏掉
    tab.listen.start("graphql")
    _recorder = GraphQLRecorder(tab, RAW_DIR, group=url, feed_only=False)
    _recorder.start()
    if reload:
        # 同一 URL 再 get 不会重新请求，先离开
        if url.split("?")[0] in (tab.url or ""):
            tab.get("https://www.facebook.com/")
            _time.sleep(2)
        tab.get(url)
        wait_doc(tab, 30)
        _time.sleep(7)

    since_ts = int(_time.mktime(_time.strptime(since, "%Y-%m-%d")))
    rounds = idle = 0
    reason = "max_rounds"
    seen_posts = {}
    t0 = _time.time()

    try:
        while rounds < max_rounds:
            rounds += 1
            scroll_once(step, pause_min, pause_max,
                        prune_every=prune_every, keep_screens=keep_screens)

            # 从已捕获的响应里提取帖子
            before = len(seen_posts)
            _harvest_search(_recorder, output, seen_posts)
            grew = len(seen_posts) - before
            log.info("轮 %s | 帖子 %s (+%s)", rounds, len(seen_posts), grew)

            if grew:
                idle = 0
            else:
                idle += 1

            # 停止：最老帖子早于 since，或连续无新增
            oldest = min((r.get("creation_time") or 0) for r in seen_posts.values()
                         if r.get("creation_time")) if seen_posts else 0
            if oldest and oldest < since_ts:
                reason = "reached_since"
                break
            if idle >= max_idle:
                reason = "no_new_content"
                break
    finally:
        # 停止前再扫一遍，避免最后一页的响应来不及被处理
        if _recorder:
            _harvest_search(_recorder, output, seen_posts)
        captured = len(_recorder.records) if _recorder else 0
        if _recorder:
            _recorder.stop()
            _recorder = None
        try:
            tab.listen.stop()
        except Exception:
            pass

    info = {"rounds": rounds, "captured": captured, "reason": reason,
            "posts": len(seen_posts),
            "elapsed": round(_time.time() - t0, 1)}
    log.info("搜索采集结束：%s", info)
    return info


def _harvest_search(recorder, output, seen_posts):
    """把监听到的搜索响应解析成帖子 JSON（去重写入）。"""
    from lib import search as searchlib
    from lib.extract import post_record

    if not recorder:
        return 0
    added = 0
    for rec in list(recorder.records):
        path = os.path.join(recorder.outdir, rec["file"])
        if not os.path.exists(path):
            continue
        try:
            tree = parse_body_tree(open(path, encoding="utf-8")
                                   .read().split(chr(10)))
        except Exception:
            continue
        nodes = list(searchlib.iter_search_nodes(tree))
        if not nodes:
            continue
        for story in nodes:
            r = post_record(story)
            pid = r["post_id"]
            if pid in seen_posts:
                continue
            seen_posts[pid] = r
            with open(os.path.join(output, pid + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(r, fh, ensure_ascii=False, indent=2)
            added += 1
    return added
