"""把译文写回 raw：给 message / body 节点加 aiTranslateText 字段。

raw 文件一旦写完就不再改动，可安全原地补字段，不覆盖任何已有字段。
"""

import glob
import json
import os
import time

from .logger import get_logger

log = get_logger("translate")


def collect(node, path, found):
    """递归找出含 text 的 message / body 节点。"""
    if isinstance(node, dict):
        for k in ("message", "body"):
            v = node.get(k)
            if isinstance(v, dict) and (v.get("text") or "").strip():
                if not v.get("aiTranslateText"):
                    found.append((path + [k], v["text"].strip()))
        for k, v in node.items():
            collect(v, path + [k], found)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            collect(v, path + [i], found)


def apply_text(root, path, zh):
    cur = root
    for p in path:
        cur = cur[p]
    cur["aiTranslateText"] = zh


def iter_files(raw_dir, skip_recent=300):
    """列出可安全处理的 raw 文件（跳过最近写入的）。"""
    now = time.time()
    for f in sorted(glob.glob(os.path.join(raw_dir, "*.jsonl"))):
        if now - os.path.getmtime(f) < skip_recent:
            continue
        yield f


def collect_jobs(raw_dir, skip_recent=300):
    """扫描 raw，返回 (jobs, 文件行缓存)。jobs = [(file, line_idx, path, text)]"""
    jobs = []
    for f in iter_files(raw_dir, skip_recent):
        for idx, line in enumerate(open(f, encoding="utf-8")):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            found = []
            collect(obj, [], found)
            for path, text in found:
                jobs.append((f, idx, path, text))
    return jobs


def write_back(jobs, mapping):
    """把译文写回 raw，返回写入字段数。"""
    by_file = {}
    for f, idx, path, text in jobs:
        if text in mapping:
            by_file.setdefault(f, {}).setdefault(idx, []).append((path, text))

    changed = 0
    for f, lines in by_file.items():
        rows = [l.rstrip("\n") for l in open(f, encoding="utf-8")]
        touched = False
        for idx, items in lines.items():
            try:
                obj = json.loads(rows[idx])
            except Exception:
                continue
            hit = False
            for path, text in items:
                apply_text(obj, path, mapping[text])
                changed += 1
                hit = True
            if hit:
                rows[idx] = json.dumps(obj, ensure_ascii=False)
                touched = True
        if touched:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
    return changed
