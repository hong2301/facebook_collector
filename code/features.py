"""功能层：由 atoms.py 的原子函数组合出的业务流程。

| 功能              | 函数                        | 参数 |
|------------------|-----------------------------|------|
| 采集小组主页帖子    | `collect_group_feed(...)`   | input_file / start / end / output / port / 采集参数 |
| 采集单个帖子+评论   | `collect_post_url(...)`     | post_url / output / sort / max_comments / 等待参数 |

参数属于功能本身，其它功能不共用。直接运行本文件即按默认参数执行。
"""

import argparse
import os
import sys

import atoms
from lib.config import INPUT_FILE, RAW_DIR, ROOT
from lib.logger import get_logger, setup
from lib.utils import read_input

log = get_logger("collector")


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
                     max_idle=6, max_rounds=500, prune_keep=40, port=9227):
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
    p.add_argument("--max-idle", type=int, default=6)
    p.add_argument("--max-rounds", type=int, default=500)
    p.add_argument("--prune-keep", type=int, default=40,
                   help="保留最近的评论节点数")
    p.add_argument("-q", "--quiet", action="store_true")

    a = ap.parse_args(argv)
    setup(quiet=a.quiet)
    params = {k: v for k, v in vars(a).items() if k not in ("cmd", "quiet")}
    if a.cmd == "group":
        collect_group_feed(**params)
    else:
        collect_post_url(**params)


if __name__ == "__main__":
    main()
