"""GraphQL 接口监听器：被动记录页面发出的所有 /api/graphql 请求与完整响应。

不主动发请求、不改参数，只旁听浏览器 → 天然安全（和真人操作完全一致）。

输出（全部落盘，可追溯）：
  data/raw/<seq>_<时间>_<doc_id>.jsonl   原始响应（JSONL，未做任何删除）
  data/raw/index.csv                     序号/时间/doc_id/响应字节/帖子数/end_cursor

用法（独立调试）：
  python -m lib.listener --scroll 5
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from urllib.parse import parse_qs

from . import session
from .config import RAW_DIR
from .logger import get_logger

log = get_logger("listener")


# 只关心真实数据接口，过滤埋点/配置类
SKIP_DOCS = {
    "28597458263257974", "40106045909008763", "25220416984279164",
    "9713919638685405", "26996952523264441", "9989124061109700",
    "9948369021930229",
}


def parse_body_tree(lines):
    """把 JSONL 各行按 path 合并成一棵树。"""
    def merge(target, path, data):
        node = target
        for i, p in enumerate(path[:-1]):
            nxt = path[i + 1]
            want = [] if isinstance(nxt, int) else {}
            if isinstance(p, int):
                if not isinstance(node, list):
                    return
                if p >= len(node):
                    node.extend([None] * (p - len(node) + 1))
                if node[p] is None:
                    node[p] = want
                node = node[p]
            else:
                if not isinstance(node, dict):
                    return
                if p not in node or node[p] is None:
                    node[p] = want
                node = node[p]
        last = path[-1]
        if isinstance(last, int):
            if not isinstance(node, list):
                return
            if last >= len(node):
                node.extend([None] * (last - len(node) + 1))
            node[last] = data
        elif isinstance(node, dict):
            # 已存在同名字典时合并，避免 deferred 段互相覆盖
            if isinstance(node.get(last), dict) and isinstance(data, dict):
                node[last].update(data)
            else:
                node[last] = data

    tree = {}
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        data = o.get("data")
        path = o.get("path")
        if path and data is not None:
            merge(tree, path, data)
        elif isinstance(data, dict) and "node" in data:
            merge(tree, ["node"], data["node"])
        elif isinstance(data, dict) and "serpResponse" in data:
            merge(tree, ["serpResponse"], data["serpResponse"])
    return tree


class GraphQLRecorder(threading.Thread):
    def __init__(self, tab, outdir=RAW_DIR, exclude_docs=None, group="",
                 feed_only=True):
        super().__init__(daemon=True)
        self.tab = tab
        self.outdir = outdir
        self.group = group or ""
        self.feed_only = feed_only
        self.exclude = set(exclude_docs or ())
        self.running = True
        self.seq = 0
        self.records = []
        self.errors = []

        os.makedirs(outdir, exist_ok=True)
        self.seq = 0

    def run(self):
        while self.running:
            try:
                p = self.tab.listen.wait(timeout=0.5)
            except Exception as e:
                self.errors.append(repr(e))
                time.sleep(0.2)
                continue
            if not p:
                continue
            try:
                self._save(p)
            except Exception as e:
                self.errors.append(repr(e))

    def _save(self, p):
        pd = p.request.postData or ""
        m = re.search(r"doc_id=(\d+)", pd)
        doc = m.group(1) if m else ""
        if doc in self.exclude:
            return
        raw = p.response.raw_body or ""
        if not raw or len(raw) < 500:
            return

        tree = parse_body_tree(raw.split(chr(10)))
        root = tree.get("node") or {}
        if not root and isinstance(tree.get("serpResponse"), dict):
            root = {"serpResponse": tree["serpResponse"]}
        if isinstance(root.get("group_feed"), dict):
            rtype = "feed"
            edges = root["group_feed"].get("edges") or []
        elif isinstance(root.get("replies_connection"), dict):
            rtype = "comments_reply"
            edges = root["replies_connection"].get("edges") or []
        elif isinstance(root.get("comment_rendering_instance_for_feed_location"), dict):
            rtype = "comments_top"
            edges = ((root["comment_rendering_instance_for_feed_location"]
                      .get("comments") or {}).get("edges") or [])
        elif isinstance(root.get("serpResponse"), dict):
            rtype = "search"
            edges = ((root["serpResponse"].get("results") or {}).get("edges") or [])
        else:
            rtype = "other"
            edges = []

        if self.feed_only and rtype != "feed":
            return

        times = []
        for e in edges:
            node = (e or {}).get("node") or {}
            ct = node.get("creation_time") or node.get("created_time")
            if ct:
                try:
                    times.append(int(ct))
                except (TypeError, ValueError):
                    pass

        self.seq += 1
        ts = time.strftime("%Y%m%d-%H%M%S")
        base = f"{ts}_{doc or 'nodoc'}"
        fn = base + ".jsonl"
        n = 1
        while os.path.exists(os.path.join(self.outdir, fn)):
            n += 1
            fn = f"{base}_{n}.jsonl"
        with open(os.path.join(self.outdir, fn), "w", encoding="utf-8") as f:
            f.write(raw)

        rec = {
            "seq": self.seq, "file": fn,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "group": self.group, "doc_id": doc, "type": rtype,
            "bytes": len(raw), "n_posts": len(edges),
            "min_ts": min(times) if times else "",
            "max_ts": max(times) if times else "",
        }
        self.records.append(rec)

    def stop(self):
        self.running = False
        self.join(timeout=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scroll", type=int, default=5)
    ap.add_argument("--pause", type=float, default=2.5)
    ap.add_argument("--step", type=int, default=1800)
    ap.add_argument("--outdir", default=RAW_DIR)
    a = ap.parse_args()

    session.open_port(9227)
    tab = session.pick_tab("groups/")

    # 记录 DOM 里出现过的帖子，用于比对监听是否漏包
    dom_ids = set()
    tab.listen.start("graphql")
    rec = GraphQLRecorder(tab, a.outdir)
    rec.start()
    log.info("监听已启动，滚动 %s 次", a.scroll)
    try:
        for i in range(a.scroll):
            tab.run_js(f"window.scrollBy(0, {a.step});")
            time.sleep(a.pause)
            ids = tab.run_js("""
const out=[];
document.querySelectorAll('a[href*="/posts/"]').forEach(a=>{
  const m=(a.getAttribute('href')||'').match(/\\/posts\\/(\\d+)/);
  if(m) out.push(m[1]);
});
return JSON.stringify(out);
""")
            try:
                dom_ids.update(json.loads(ids or "[]"))
            except Exception:
                pass
            log.info("滚动 %s/%s  DOM 帖子 %s", i + 1, a.scroll, len(dom_ids))
    finally:
        time.sleep(2)
        rec.stop()
        tab.listen.stop()

    api_ids = set()
    for r in rec.records:
        if r["post_ids"]:
            api_ids.update(r["post_ids"].split(";"))
    log.info("捕获请求 %s 个，异常 %s", len(rec.records), len(rec.errors))
    log.info("接口 post_id %s 个 | DOM 抓到 %s 个", len(api_ids), len(dom_ids))
    missing = dom_ids - api_ids
    log.info("DOM 有但接口没抓到: %s", len(missing))
    if missing:
        log.debug("例: %s", list(missing)[:10])
    for r in rec.records[:12]:
        log.info("  %3s doc=%s %7sB posts=%s next=%s %s",
                 r["seq"], r["doc_id"], r["resp_bytes"], r["n_posts"],
                 r["has_next"], r["friendly_name"][:40])
    if rec.errors:
        log.warning("errors: %s", rec.errors[:5])


if __name__ == "__main__":
    main()
