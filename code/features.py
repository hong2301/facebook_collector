"""功能层：由 atoms.py 的原子函数组合出的业务流程。

| 功能              | 函数                        | 参数 |
|------------------|-----------------------------|------|
| 采集小组主页帖子    | `collect_group_feed(...)`   | input_file / start / end / output / port / 采集参数 |
| 采集单个帖子+评论   | `collect_post_url(...)`     | post_url / output / sort / max_comments / 等待参数 |
| 批量采集帖子        | `collect_posts(...)`        | urls 或 input_file / start / end / output / 采集参数 |
| 生成待补采清单      | `plan_missing_posts(...)`   | posts_dir / out_file / limit |
| 翻译                | `translate_dataset(...)`    | kind=post/comment/all / limit |
| 翻译回写 raw        | `translate_raw(...)`        | raw_dir / engine / limit |
| 关键词搜帖          | `collect_keyword(...)`      | keyword / kind / 筛选 / since |
| 关键词按月切片搜     | `collect_keyword_slices(...)` | keyword / years / months / output |

参数属于功能本身，其它功能不共用。直接运行本文件即按默认参数执行。
"""

import argparse
import csv
import glob
import json
import os
import sys

import atoms
from lib.config import CODE_DIR, INPUT_FILE, RAW_DIR, ROOT
from lib.logger import get_logger, setup
from lib.utils import read_input

log = get_logger("collector")

INPUT_POSTS_FILE = os.path.join(CODE_DIR, "input_posts.csv")
POSTS_OUTPUT_DIR = os.path.join(ROOT, "data", "posts")


def collect_group_feed(input_file=INPUT_FILE, start=0, end=0, output=RAW_DIR,
                       port=9227, since="2025-01-01",
                       step=1800, pause_min=1.0, pause_max=3.0,
                       max_idle=10, max_rounds=99999,
                       prune_every=4, keep_screens=8, reload=True):
    """采集一个输入清单里的全部小组主页帖子。

    Args:
        input_file:  输入清单，一行一个小组链接
        start/end:   清单切片，end=0 表示到末尾
        output:      接口原始响应目录
        port:        浏览器调试端口
        其余:        转发给 atoms.collect_group_posts 的采集参数

    Returns:
        (成功数, 失败数)
    """
    urls = read_input(input_file)
    urls = urls[start:end] if end > 0 else urls[start:]
    if not urls:
        log.error("没有可用的输入链接（文件内 %s 条，切片 [%s:%s]）",
                  len(read_input(input_file)), start, end or "末尾")
        return 0, 0

    os.makedirs(output, exist_ok=True)
    log.info("端口=%s 输出=%s 链接=%s 停顿=%.1f-%.1fs 下限=%s",
             port, output, len(urls), pause_min, pause_max, since)

    atoms.open_port(port)
    if not atoms.check_login():
        return 0, len(urls)

    ok = fail = 0
    for i, url in enumerate(urls, 1):
        log.info("任务 %s/%s：%s", i, len(urls), url)
        try:
            atoms.collect_group_posts(
                url, output, since=since, step=step,
                pause_min=pause_min, pause_max=pause_max,
                max_idle=max_idle, max_rounds=max_rounds,
                prune_every=prune_every, keep_screens=keep_screens,
                reload=reload)
            ok += 1
        except KeyboardInterrupt:
            log.warning("用户中断，停止后续任务")
            break
        except Exception:
            log.exception("任务失败：%s", url)
            fail += 1

    log.info("全部完成：成功 %s，失败 %s", ok, fail)
    return ok, fail



def collect_post_url(post_url, output=RAW_DIR, sort="all", max_comments=0,
                     pause_min=1.0, pause_max=3.0,
                     scroll_pause_min=1.0, scroll_pause_max=3.0,
                     max_idle=5, max_rounds=500, prune_keep=40, port=9227):
    """采集单个帖子：帖子基本数据 + 完整评论。

    Args:
        post_url:       帖子链接
        output:         输出目录（raw 与解析结果都写这里）
        sort:           评论排序 most_relevant / newest / all
        max_comments:   评论数量上限，0 不限
        pause_min/max:  点击展开后的随机等待（秒）
        scroll_pause_min/max: 每次滚动后的随机等待（秒）
    """
    os.makedirs(output, exist_ok=True)
    log.info("端口=%s 输出=%s 排序=%s 评论上限=%s 滚动等待=%.1f-%.1fs",
             port, output, sort, max_comments or "不限",
             scroll_pause_min, scroll_pause_max)

    atoms.open_port(port)
    if not atoms.check_login():
        return {}

    return atoms.collect_post(
        post_url, output, sort=sort, max_comments=max_comments,
        pause_min=pause_min, pause_max=pause_max,
        scroll_pause_min=scroll_pause_min, scroll_pause_max=scroll_pause_max,
        max_idle=max_idle, max_rounds=max_rounds, prune_keep=prune_keep)



def collect_posts(urls=None, input_file=None, start=0, end=0,
                  output=None, port=9227, sort="all", max_comments=0,
                  pause_min=1.0, pause_max=3.0,
                  scroll_pause_min=1.0, scroll_pause_max=3.0,
                  max_idle=5, max_rounds=500, prune_keep=40):
    """批量采集帖子：链接来自命令行或清单文件（CSV 的 url 列）。

    Returns:
        (成功数, 失败数)
    """
    output = output or POSTS_OUTPUT_DIR
    if urls:
        links = list(urls)
    else:
        try:
            links = read_input(input_file or INPUT_POSTS_FILE)
        except OSError as exc:
            log.error("读取帖子清单失败：%s", exc)
            return 0, 0

    links = links[start:end] if end > 0 else links[start:]
    if not links:
        log.error("没有可用的帖子链接（总计 %s 条，切片 [%s:%s]）",
                  len(urls or []), start, end or "末尾")
        return 0, 0

    os.makedirs(output, exist_ok=True)
    log.info("端口=%s 输出=%s 帖子=%s 排序=%s 评论上限=%s",
             port, output, len(links), sort, max_comments or "不限")

    atoms.open_port(port)
    if not atoms.check_login():
        return 0, len(links)

    ok = fail = 0
    for i, url in enumerate(links, 1):
        log.info("帖子 %s/%s：%s", i, len(links), url)
        try:
            atoms.collect_post(
                url, output, sort=sort, max_comments=max_comments,
                pause_min=pause_min, pause_max=pause_max,
                scroll_pause_min=scroll_pause_min, scroll_pause_max=scroll_pause_max,
                max_idle=max_idle, max_rounds=max_rounds, prune_keep=prune_keep)
            ok += 1
        except KeyboardInterrupt:
            log.warning("用户中断，停止后续帖子")
            break
        except Exception:
            log.exception("帖子采集失败：%s", url)
            fail += 1

    log.info("全部完成：成功 %s，失败 %s", ok, fail)
    return ok, fail



def build_posts_from_raw(raw_dir=RAW_DIR, output=None):
    """整理 raw → 帖子 JSON + 评论 CSV（批量，零请求）。"""
    raw_dir = raw_dir or RAW_DIR
    output = output or POSTS_OUTPUT_DIR
    log.info("读取 raw：%s -> 输出：%s", raw_dir, output)
    n_posts, n_cmts = atoms.raw_to_posts(raw_dir, output)
    log.info("整理完成：帖子 %s，预览评论 %s", n_posts, n_cmts)
    return n_posts, n_cmts


def plan_missing_posts(posts_dir=None, out_file=None, limit=0):
    """生成待补采清单：只保留「有评论且还没采全」的帖子。"""
    posts_dir = posts_dir or POSTS_OUTPUT_DIR
    out_file = out_file or INPUT_POSTS_FILE
    no_comment = full = 0
    rows = []
    for path in glob.glob(os.path.join(posts_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        total = d.get("comment_count") or 0
        have = d.get("comment_collected") or 0
        if total == 0:                 # 评论值为 0，不进清单
            no_comment += 1
            continue
        if have >= total:              # 已经采全
            full += 1
            continue
        rows.append((d["post_url"], total - have, d["post_time"]))

    rows.sort(key=lambda r: r[1])
    if limit:
        rows = rows[:limit]
    with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "note"])
        for url, need, ts in rows:
            w.writerow([url, f"missing={need} {ts}"])

    log.info("评论为0 %s | 已采全 %s | 待补采 %s（%s）",
             no_comment, full, len(rows), out_file)
    return len(rows)



def translate_dataset(kind="all", limit=0, pause=1.2):
    """给 posts / comments 补充中文译文（text_zh）。

    Args:
        kind: post / comment / all
        limit: 每类最多处理多少条，0 表示全部
    """
    from lib.translate import translate_texts

    posts_dir = POSTS_OUTPUT_DIR
    comments_dir = os.path.join(ROOT, "data", "comments")

    if kind in ("post", "all"):
        files = sorted(glob.glob(os.path.join(posts_dir, "*.json")))
        if limit:
            files = [f for f in files if not _has_zh(f)][:limit]
        else:
            files = [f for f in files if not _has_zh(f)]
        texts = []
        docs = []
        for f in files:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            t = (d.get("text") or "").strip()
            if t:
                texts.append(t)
                docs.append((f, d))
        log.info("帖子待翻译 %s 条", len(texts))
        trans = translate_texts(texts, pause=pause) if texts else {}
        n = 0
        for f, d in docs:
            zh = trans.get((d.get("text") or "").strip())
            if zh:
                d["text_zh"] = zh
                with open(f, "w", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False, indent=2)
                n += 1
        log.info("帖子已翻译 %s / %s", n, len(texts))

    if kind in ("comment", "all"):
        files = sorted(glob.glob(os.path.join(comments_dir, "*.csv")))
        rows_all = []
        for f in files:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            need = [r for r in rows if (r.get("text") or "").strip()
                    and not (r.get("text_zh") or "").strip()]
            if need:
                rows_all.append((f, rows, need))
        total = sum(len(x[2]) for x in rows_all)
        log.info("评论待翻译 %s 条（%s 个文件）", total, len(rows_all))
        texts = [r["text"].strip() for _, _, need in rows_all for r in need]
        if limit:
            texts = texts[:limit]
        trans = translate_texts(texts, pause=pause) if texts else {}
        n = 0
        for f, rows, need in rows_all:
            changed = False
            for r in rows:
                src = (r.get("text") or "").strip()
                zh = trans.get(src)
                if zh and not (r.get("text_zh") or "").strip():
                    r["text_zh"] = zh
                    n += 1
                    changed = True
            if changed:
                cols = list(rows[0].keys())
                with open(f, "w", encoding="utf-8-sig", newline="") as fh:
                    w = csv.DictWriter(fh, cols)
                    w.writeheader()
                    w.writerows(rows)
        log.info("评论已翻译 %s / %s", n, len(texts))


def _has_zh(path):
    try:
        with open(path, encoding="utf-8") as f:
            return bool(json.load(f).get("text_zh"))
    except Exception:
        return False



def translate_raw(raw_dir=None, limit=0):
    """把 raw 里的帖子/评论正文翻译后写回 aiTranslateText（不覆盖原字段）。"""
    from lib.config import RAW_DIR
    raw_dir = raw_dir or RAW_DIR
    log.info("raw 翻译：%s", raw_dir)
    total, uniq, written = atoms.translate_raw_fields(raw_dir, limit=limit)
    log.info("完成：字段 %s，唯一文本 %s，写入 %s", total, uniq, written)
    return written



def collect_keyword(keyword, kind="top", since="2025-01-01", output=None,
                    recent=False, seen=False, year=None, month=None,
                    author_me=False, pause_min=1.0, pause_max=3.0, port=9227):
    """按关键词搜索并采集帖子。

    Args:
        keyword:   搜索词
        kind:      top（综合）/ posts（帖子）
        since:     采到这个日期之前就停
        recent:    只看近期帖子
        seen:      只看你看过的帖子
        year/month: 按发布日期筛选
        author_me: 只看自己发的
    """
    from lib.config import POSTS_DIR
    from lib import search as searchlib

    url = searchlib.build_search_url(
        keyword, kind=kind, recent=recent, seen=seen,
        year=year, month=month, author_me=author_me)
    output = output or POSTS_DIR
    log.info("关键词=%s | 类型=%s | since=%s", keyword, kind, since)
    log.info("搜索链接：%s", url)

    atoms.open_port(port)
    if not atoms.check_login():
        return {}

    return atoms.collect_search_posts(
        url, output=output, since=since,
        pause_min=pause_min, pause_max=pause_max)



def collect_keyword_slices(keyword, kind="posts", years=None, months=None,
                           output=None, port=9227, pause=2.0,
                           pause_min=1.0, pause_max=2.0):
    """按年月切片批量搜索：每个月单独搜一次，规避搜索结果条数上限。

    Args:
        years:  要搜的年份，默认 [2025, 2026]
        months: 要搜的月份，默认 1-12
        pause:  每个切片之间的间隔（秒）

    Returns:
        (总帖子数, 切片数)
    """
    import time as _time
    from lib.config import POSTS_DIR
    from lib import search as searchlib

    years = years or [2025, 2026]
    months = months or list(range(1, 13))
    output = output or POSTS_DIR
    os.makedirs(output, exist_ok=True)

    # 已存在的帖子不重复采
    seen = {f[:-5] for f in os.listdir(output) if f.endswith(".json")}
    log.info("已有帖子 %s，关键词=%s，切片 %s 年 × %s 月",
             len(seen), keyword, len(years), len(months))

    atoms.open_port(port)
    if not atoms.check_login():
        return 0, 0

    total = 0
    slices = 0
    for y in years:
        for m in months:
            url = searchlib.build_search_url(keyword, kind=kind, year=y, month=m)
            slices += 1
            log.info("切片 %s/%s：%s", slices, len(years) * len(months), url[:110])
            try:
                info = atoms.collect_search_posts(
                    url, output=output, since=f"{y}-{m:02d}-01",
                    pause_min=pause_min, pause_max=pause_max)
                total += info.get("posts", 0)
                log.info("  本切片 %s 帖（累计 %s）", info.get("posts", 0), total)
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("切片失败：%s-%s", y, m)
            _time.sleep(pause)

    log.info("按月搜索完成：%s 个切片，共 %s 帖", slices, total)
    return total, slices


def main(argv=None):
    ap = argparse.ArgumentParser(description="Facebook 采集功能")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("group", help="采集小组主页帖子")
    g.add_argument("-i", "--input-file", default=INPUT_FILE,
                   help="输入清单文件，一行一个小组链接")
    g.add_argument("--start", type=int, default=0)
    g.add_argument("--end", type=int, default=0, help="0=末尾")
    g.add_argument("-o", "--output", default=RAW_DIR)
    g.add_argument("--port", type=int, default=9227)
    g.add_argument("--since", default="2025-01-01")
    g.add_argument("--step", type=int, default=1800)
    g.add_argument("--pause-min", type=float, default=1.0)
    g.add_argument("--pause-max", type=float, default=3.0)
    g.add_argument("--max-idle", type=int, default=10)
    g.add_argument("--max-rounds", type=int, default=99999)
    g.add_argument("--prune-every", type=int, default=4)
    g.add_argument("--keep-screens", type=int, default=8)
    g.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("post", help="采集单个帖子 + 评论")
    p.add_argument("post_url", metavar="URL", help="帖子链接")
    p.add_argument("-o", "--output", default=os.path.join(ROOT, "data", "posts"))
    p.add_argument("--port", type=int, default=9227)
    p.add_argument("--sort", default="all",
                   choices=["most_relevant", "newest", "all"],
                   help="评论排序")
    p.add_argument("--max-comments", type=int, default=0, help="0=不限")
    p.add_argument("--pause-min", type=float, default=1.0,
                   help="点击展开后的等待下限（秒）")
    p.add_argument("--pause-max", type=float, default=3.0)
    p.add_argument("--scroll-pause-min", type=float, default=1.0,
                   help="每次滚动后的等待下限（秒）")
    p.add_argument("--scroll-pause-max", type=float, default=3.0)
    p.add_argument("--max-idle", type=int, default=5)
    p.add_argument("--max-rounds", type=int, default=500)
    p.add_argument("--prune-keep", type=int, default=40,
                   help="保留最近的评论节点数")
    p.add_argument("-q", "--quiet", action="store_true")

    b = sub.add_parser("posts", help="批量采集帖子 + 评论")
    b.add_argument("urls", nargs="*", help="帖子链接，可多个；留空则读清单文件")
    b.add_argument("-i", "--input-file", default=INPUT_POSTS_FILE,
                   help="帖子清单 CSV（url 列）")
    b.add_argument("--start", type=int, default=0)
    b.add_argument("--end", type=int, default=0, help="0=末尾")
    b.add_argument("-o", "--output", default=POSTS_OUTPUT_DIR)
    b.add_argument("--port", type=int, default=9227)
    b.add_argument("--sort", default="all",
                   choices=["most_relevant", "newest", "all"])
    b.add_argument("--max-comments", type=int, default=0, help="0=不限")
    b.add_argument("--pause-min", type=float, default=1.0)
    b.add_argument("--pause-max", type=float, default=3.0)
    b.add_argument("--scroll-pause-min", type=float, default=1.0)
    b.add_argument("--scroll-pause-max", type=float, default=3.0)
    b.add_argument("--max-idle", type=int, default=5)
    b.add_argument("--max-rounds", type=int, default=500)
    b.add_argument("--prune-keep", type=int, default=40)
    b.add_argument("-q", "--quiet", action="store_true")

    bd = sub.add_parser("build", help="整理 raw → 帖子 JSON + 评论 CSV")
    bd.add_argument("--raw-dir", default=RAW_DIR)
    bd.add_argument("-o", "--output", default=POSTS_OUTPUT_DIR)
    bd.add_argument("-q", "--quiet", action="store_true")

    m = sub.add_parser("plan", help="生成待补采帖子清单")
    m.add_argument("--posts-dir", default=POSTS_OUTPUT_DIR)
    m.add_argument("-o", "--out-file", default=INPUT_POSTS_FILE)
    m.add_argument("--limit", type=int, default=0, help="0=全部")
    m.add_argument("-q", "--quiet", action="store_true")

    tr = sub.add_parser("translate", help="翻译 posts/comments 的正文")
    tr.add_argument("--kind", choices=["post", "comment", "all"], default="all")
    tr.add_argument("--limit", type=int, default=0, help="每类最多处理条数")
    tr.add_argument("--pause", type=float, default=1.2)
    tr.add_argument("-q", "--quiet", action="store_true")

    trr = sub.add_parser("translate-raw", help="翻译写回 raw 的 aiTranslateText")
    trr.add_argument("--raw-dir", default=RAW_DIR)
    trr.add_argument("--limit", type=int, default=0)
    trr.add_argument("-q", "--quiet", action="store_true")

    kw = sub.add_parser("search", help="按关键词搜索采集帖子")
    kw.add_argument("keyword", help="搜索词")
    kw.add_argument("--kind", choices=["top", "posts"], default="top")
    kw.add_argument("--since", default="2025-01-01")
    kw.add_argument("-o", "--output", default=POSTS_OUTPUT_DIR)
    kw.add_argument("--recent", action="store_true", help="只看近期帖子")
    kw.add_argument("--seen", action="store_true", help="只看你看过的")
    kw.add_argument("--year", type=int, help="按发布年份筛选")
    kw.add_argument("--month", type=int, help="搭配 --year 用")
    kw.add_argument("--author-me", action="store_true", help="只看自己发的")
    kw.add_argument("--port", type=int, default=9227)
    kw.add_argument("--pause-min", type=float, default=1.0)
    kw.add_argument("--pause-max", type=float, default=3.0)
    kw.add_argument("-q", "--quiet", action="store_true")

    kws = sub.add_parser("search-slices", help="按年月切片批量搜索")
    kws.add_argument("keyword")
    kws.add_argument("--kind", choices=["top", "posts"], default="posts")
    kws.add_argument("--years", nargs="*", type=int, default=[2025, 2026])
    kws.add_argument("--months", nargs="*", type=int, default=list(range(1, 13)))
    kws.add_argument("-o", "--output", default=POSTS_OUTPUT_DIR)
    kws.add_argument("--port", type=int, default=9227)
    kws.add_argument("--pause", type=float, default=2.0)
    kws.add_argument("-q", "--quiet", action="store_true")

    a = ap.parse_args(argv)
    setup(quiet=a.quiet)
    params = {k: v for k, v in vars(a).items() if k not in ("cmd", "quiet")}
    if a.cmd == "group":
        collect_group_feed(**params)
    elif a.cmd == "post":
        collect_post_url(**params)
    elif a.cmd == "build":
        build_posts_from_raw(**params)
    elif a.cmd == "search-slices":
        collect_keyword_slices(**params)
    elif a.cmd == "search":
        collect_keyword(**params)
    elif a.cmd == "translate-raw":
        translate_raw(**params)
    elif a.cmd == "translate":
        translate_dataset(**params)
    elif a.cmd == "plan":
        plan_missing_posts(**params)
    else:
        collect_posts(**params)


if __name__ == "__main__":
    main()
