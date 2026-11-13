"""功能层：由 atoms.py 的原子函数组合出的业务流程。

| 功能              | 函数                     | 参数                                       |
|------------------|--------------------------|--------------------------------------------|
| 采集小组主页帖子    | collect_group_feed(...)  | input_file / start / end / output / port / 采集参数 |

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


def main(argv=None):
    ap = argparse.ArgumentParser(description="采集小组主页帖子")
    ap.add_argument("-i", "--input-file", default=INPUT_FILE,
                    help="输入清单文件，一行一个小组链接")
    ap.add_argument("--start", type=int, default=0, help="起始索引（含）")
    ap.add_argument("--end", type=int, default=0, help="结束索引（不含），0=末尾")
    ap.add_argument("-o", "--output", default=RAW_DIR, help="原始数据输出目录")
    ap.add_argument("--port", type=int, default=9227, help="浏览器调试端口")
    ap.add_argument("--since", default="2025-01-01", help="采集下限日期")
    ap.add_argument("--step", type=int, default=1800, help="每次滚动像素")
    ap.add_argument("--pause-min", type=float, default=1.0, help="停顿下限（秒）")
    ap.add_argument("--pause-max", type=float, default=3.0, help="停顿上限（秒）")
    ap.add_argument("--max-idle", type=int, default=10, help="连续无新内容轮数上限")
    ap.add_argument("--max-rounds", type=int, default=99999, help="滚动轮数硬上限")
    ap.add_argument("--prune-every", type=int, default=4, help="每 N 轮清理旧 DOM")
    ap.add_argument("--keep-screens", type=int, default=8, help="保留视口上方屏数")
    ap.add_argument("--resume", dest="reload", action="store_false",
                    help="接续模式：沿用当前页面位置，不重新加载")
    ap.add_argument("-q", "--quiet", action="store_true", help="控制台只输出警告")
    a = ap.parse_args(argv)

    setup(quiet=a.quiet)
    params = vars(a)
    params.pop("quiet", None)
    collect_group_feed(**params)


if __name__ == "__main__":
    main()
