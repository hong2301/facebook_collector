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
import time

from lib import session
from lib.auth import is_logged_in
from lib.browser import wait_doc
from lib.config import RAW_DIR, ROOT
from lib.listener import GraphQLRecorder
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
    tab = session.get_tab()
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


def collect_post(post_url, output=RAW_DIR, sort="all",
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
    os.makedirs(output, exist_ok=True)

    post_id = postlib.parse_post_id(post_url)
    base = postlib.extract_post(post_id)

    conn = _recorder
    tab.listen.start("graphql")
    _recorder = GraphQLRecorder(tab, output, group=post_url, feed_only=False)
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


def raw_to_posts(raw_dir=RAW_DIR, output=None):
    """【原子】读取 feed 原始响应，输出帖子 JSON + 评论 CSV（零请求）。

    每帖一份：posts/<post_id>.json、comments/<post_id>.csv，另附 index.csv。

    Returns:
        (帖子数, 评论数)
    """
    output = output or os.path.join(ROOT, "data", "posts")
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

    return extractlib.write_output(output, list(posts.values()),
                                   list(comments.values()))
