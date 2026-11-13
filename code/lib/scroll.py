"""滚动动作：单次滚动、循环滚动、清理已滚过的帖子 DOM。

日志约定：
- scroll_once  每次滚动：DEBUG（y / height / articles）
- prune_dom    删除节点：INFO（删除数量，仅 >0 时）
- scroll_until 每 N 轮汇总 INFO，结束时 INFO 汇总（轮数 / 总删除 / 停止原因 / 耗时）
"""

import json
import time

from .logger import get_logger
from .session import get_tab
from .utils import pick_pause

log = get_logger("collector")

# 删除视口上方 keep_screens 屏以外、已滚过的顶层帖子节点
JS_PRUNE = """
const keep = %d;
const y = window.scrollY, vh = window.innerHeight;
const arts = [...document.querySelectorAll('div[role=article]')]
  .filter(a => !(a.parentElement && a.parentElement.closest('div[role=article]')));
let removed = 0;
for (const a of arts) {
  const bottom = a.getBoundingClientRect().bottom + y;
  if (bottom < y - vh * keep) { a.remove(); removed++; }
}
return removed;
"""

JS_STATE = """
return JSON.stringify({
  y: Math.round(window.scrollY),
  h: document.body.scrollHeight,
  vh: window.innerHeight,
  arts: document.querySelectorAll('div[role=article]').length
});
"""

_prune_round = {"n": 0}


def page_state(tab=None):
    """当前页面滚动状态：y / height / viewport / article 数。"""
    tab = tab or get_tab()
    try:
        return json.loads(tab.run_js(JS_STATE) or "{}")
    except Exception:
        return {}


def prune_dom(keep_screens=3, tab=None):
    """移除已滚过区域的帖子节点，返回删除个数。"""
    tab = tab or get_tab()
    try:
        removed = int(tab.run_js(JS_PRUNE % keep_screens) or 0)
    except Exception as exc:
        log.debug("DOM 清理失败：%r", exc)
        return 0
    if removed:
        log.info("清理已滚过的帖子节点 %s 个（保留视口上方 %s 屏）",
                 removed, keep_screens)
    return removed


def scroll_once(step=1800, pause_min=1.0, pause_max=3.0, tab=None,
                prune_every=4, keep_screens=8):
    """向下滚动一次并随机停顿；每 prune_every 次顺手清理旧 DOM。"""
    tab = tab or get_tab()
    tab.run_js(f"window.scrollBy(0, {step});")
    time.sleep(pick_pause(pause_min, pause_max))

    _prune_round["n"] += 1
    if prune_every and _prune_round["n"] % prune_every == 0:
        prune_dom(keep_screens, tab)

    st = page_state(tab)
    log.debug("滚动 step=%s -> y=%s h=%s articles=%s",
              step, st.get("y"), st.get("h"), st.get("arts"))
    return st.get("h", 0)


def at_bottom(tab=None, tolerance=200):
    """是否已滚到文档底部。"""
    st = page_state(tab or get_tab())
    return st.get("y", 0) + st.get("vh", 0) >= st.get("h", 0) - tolerance


def scroll_until(step=1800, pause_min=1.0, pause_max=3.0,
                 max_idle=5, max_rounds=10000,
                 prune_every=4, keep_screens=8,
                 stop_check=None, tab=None, log_every=10):
    """循环滚动直到满足停止条件，返回统计信息。

    停止条件（任一）：
      - stop_check() 返回 True（如已滚到下限日期）
      - 连续 max_idle 轮到底且无新增高度
      - 达到 max_rounds
    """
    tab = tab or get_tab()
    rounds = idle = removed_total = 0
    reason = "max_rounds"
    t0 = time.time()
    h_prev = page_state(tab).get("h", 0)

    while rounds < max_rounds:
        rounds += 1
        removed_before = 0
        yield_h = scroll_once(step, pause_min, pause_max, tab,
                              prune_every, keep_screens)
        st = page_state(tab)
        grew = max(0, st.get("h", 0) - h_prev)
        h_prev = st.get("h", 0)

        if stop_check and stop_check():
            reason = "stop_check"
            break

        if at_bottom(tab) and grew == 0:
            idle += 1
            if idle >= max_idle:
                reason = "no_new_content"
                break
        else:
            idle = 0

        if log_every and rounds % log_every == 0:
            log.info("滚动 %s 轮 | y=%s h=%s articles=%s 本轮+%s idle=%s "
                     "耗时=%.0fs", rounds, st.get("y"), st.get("h"),
                     st.get("arts"), grew, idle, time.time() - t0)

    info = {
        "rounds": rounds,
        "idle": idle,
        "reason": reason,
        "elapsed": round(time.time() - t0, 1),
        "y": page_state(tab).get("y", 0),
    }
    log.info("滚动结束：%s 轮，停止原因=%s，耗时=%ss，最终 y=%s",
             info["rounds"], info["reason"], info["elapsed"], info["y"])
    return info
