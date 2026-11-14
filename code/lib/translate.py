"""翻译：英文 → 中文，走共享文件夹里的 GLM 模块（免费额度）。

- 批量：每批 8 条，减少请求次数
- 缓存：data/translate_cache.json，已翻过的不重复
- 只写 posts / comments 的 *_zh 字段，不改 raw
"""

import json
import os
import re
import sys
import time

from .config import DATA_DIR
from .logger import get_logger

log = get_logger("translate")

GLM_ROOT = r"D:/homeShare/仓库/头歌闯关王"
CACHE_PATH = os.path.join(DATA_DIR, "translate_cache.json")
BATCH_SIZE = 20
PROXY = "http://192.168.31.238:7897"

_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
        else:
            _cache = {}
    return _cache


def save_cache():
    c = _load_cache()
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)
    return len(c)


def _ai():
    if GLM_ROOT not in sys.path:
        sys.path.insert(0, GLM_ROOT)
    from modules import aiAsk
    return aiAsk


PROMPT = """把下面每条英文翻译成简体中文，保持原意和语气，不要解释。
输出格式：每行一条，形如  序号|||译文
共 %d 条，序号从 1 开始，必须输出 %d 行，不要任何其他内容。

输入：
%s
"""


def _translate_batch(texts):
    """一次请求翻译多条，返回译文列表（长度与输入一致）。"""
    lines_in = chr(10).join(f"{i+1}. {t}" for i, t in enumerate(texts))
    aiAsk = _ai()
    r = aiAsk(PROMPT % (len(texts), len(texts), lines_in),
              thinking=False, timeout=60, total_timeout=90,
              proxy=PROXY, retries=2, retry_interval=5.0)
    if r.get("status") != "success":
        log.warning("翻译请求失败：%s", (r.get("data") or {}).get("error_type"))
        return None

    content = ((r.get("data") or {}).get("content") or "").strip()
    out = {}
    for line in content.split(chr(10)):
        if "|||" not in line:
            continue
        head, _, rest = line.partition("|||")
        head = head.strip().strip("`").strip()
        if head.isdigit():
            out[int(head)] = rest.strip().strip("`").strip()
    if len(out) == len(texts):
        return [out[i + 1] for i in range(len(texts))]

    lines = [x.strip() for x in content.split(chr(10)) if x.strip()]
    if len(lines) == len(texts):
        return lines
    log.warning("批量翻译解析失败（%s 条 -> %s 段）", len(texts), len(out) or len(lines))
    return None


def translate_texts(texts, pause=10.0, use_cache=True):
    """翻译一批文本，返回 {原文: 译文}。"""
    cache = _load_cache() if use_cache else {}
    todo = [t for t in dict.fromkeys(texts) if t and t not in cache]
    if not todo:
        return {t: cache[t] for t in texts if t in cache}

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        out = _translate_batch(batch)
        if out is None:
            time.sleep(3)
            out = _translate_batch(batch)
        if out is None:
            log.warning("跳过一批（%s 条）", len(batch))
            continue
        for src, dst in zip(batch, out):
            cache[src] = dst
        if (i // BATCH_SIZE + 1) % 10 == 0:
            save_cache()
            log.info("已翻译 %s/%s", i + len(batch), len(todo))
        time.sleep(pause)
    if use_cache:
        save_cache()
    return {t: cache[t] for t in texts if t in cache}
