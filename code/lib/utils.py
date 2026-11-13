"""通用工具：输入清单读取、索引切片、随机停顿、URL 规范化。"""

import csv
import random


def read_input(path):
    """读取输入清单 CSV，返回链接列表。

    支持两种形态：
      - 有表头且含 url 列：取该列
      - 无表头：取第一列
    忽略空行与 # 注释。
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f)
                if r and not str(r[0]).strip().startswith("#")]
    if not rows:
        return []
    header = [str(c).strip().lower() for c in rows[0]]
    if "url" in header:
        idx = header.index("url")
        body = rows[1:]
    else:
        idx = 0
        body = rows
    out = []
    for r in body:
        if idx < len(r):
            v = str(r[idx]).strip()
            if v and not v.startswith("#"):
                out.append(v)
    return out


def select_groups(urls, start, end):
    """按索引切片；end=0 表示到末尾。"""
    total = len(urls)
    if not total:
        return []
    start = max(0, min(start, total))
    end = total if end <= 0 else min(end, total)
    return urls[start:end] if start < end else []


def normalize_url(url):
    """只补协议，查询参数由 input 决定（见 doc/url-parameters.md）。"""
    u = (url or "").strip()
    if not u:
        return ""
    return u if u.startswith("http") else "https://" + u


def pick_pause(lo, hi):
    """滚动间隔随机化，避免机械节奏。"""
    lo, hi = min(lo, hi), max(lo, hi)
    return random.uniform(lo, hi)
