"""帖子页相关：帖子基本数据、评论排序、展开回复、滚动、层级安全清理。"""

import csv
import json
import os
import random
import re
import time

from .logger import get_logger
from .session import get_tab

log = get_logger("collector")

JS_FIND_POST = """
const pid = "%s";
const arts = [...document.querySelectorAll('div[role=article]')];
return arts.find(a => (a.innerHTML || '').indexOf(pid) >= 0) ? true : false;
"""

JS_POST_TEXT = """
const NL = String.fromCharCode(10);
const arts = [...document.querySelectorAll('div[role=article]')]
  .filter(a => (a.innerText || '').length > 400);
if (!arts.length) return JSON.stringify({lines: [], aria: []});
arts.sort((a, b) => (b.innerText || '').length - (a.innerText || '').length);
const a = arts[0];
const aria = [...a.querySelectorAll('[aria-label]')]
  .map(e => e.getAttribute('aria-label') || '')
  .filter(L => /评论|赞|分享|comment|like|share/i.test(L));
return JSON.stringify({lines: (a.innerText || '').split(NL), aria});
"""

JS_SCROLLER = """
const sc = [...document.querySelectorAll('div')]
  .filter(d => d.scrollHeight - d.clientHeight > 120)
  .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
if (!sc) { window.scrollTo(0, document.body.scrollHeight); return document.body.scrollHeight; }
sc.scrollTop = sc.scrollHeight;
return sc.scrollHeight;
"""

JS_SCROLLER_STATE = """
const sc = [...document.querySelectorAll('div')]
  .filter(d => d.scrollHeight - d.clientHeight > 120)
  .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
if (!sc) {
  const y = window.scrollY, h = document.body.scrollHeight, vh = window.innerHeight;
  return JSON.stringify({st: Math.round(y), sh: h, ch: vh,
                         atBottom: y + vh >= h - 50, fallback: true});
}
return JSON.stringify({
  st: Math.round(sc.scrollTop), sh: sc.scrollHeight, ch: sc.clientHeight,
  atBottom: sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 50
});
"""

JS_SORT_BUTTON = """
const want = "%s";
const btns = [...document.querySelectorAll('div[role=button]')];
const b = btns.find(e => (e.innerText || '').trim() === want);
if (!b) return false;
b.click();
return true;
"""

JS_SORT_ITEM = """
const want = "%s";
const items = [...document.querySelectorAll('div[role=menuitem]')];
const it = items.find(e => (e.innerText || '').trim().indexOf(want) === 0);
if (!it) return false;
it.click();
return true;
"""

# 展开按钮：全部N条回复 / 查看N条回复 / 查看更多评论 / 查看之前的评论
JS_EXPAND = r"""
const pats = [
  /^全部\\s*\\d+\\s*条回复$/, /^查看\\s*\\d+\\s*条回复$/,
  /^查看更多评论$/, /^查看之前的评论$/,
  /^See \\d+ more repl/i, /^View \\d+ more repl/i, /^View previous comments$/,
  /^View more comments$/
];
let n = 0;
document.querySelectorAll('div[role=button],span[role=button]').forEach(e => {
  const t = (e.innerText || '').trim();
  if (t && t.length < 30 && pats.some(p => p.test(t))) {
    try { e.click(); n++; } catch (x) {}
  }
});
return n;
"""

# 层级安全清理：
#   1) 绝不删帖子本体
#   2) 只删「自身及子孙都没有待展开按钮」的评论节点
#   3) 从最早（最上面）开始删，保留最近 keep 个评论
JS_PRUNE_SAFE = r"""
const keep = %d;
const post = [...document.querySelectorAll('div[role=article]')]
  .filter(a => (a.innerText || '').length > 400)
  .sort((a, b) => (b.innerText || '').length - (a.innerText || '').length)[0];
if (!post) return 0;

const expandRe = /(全部\s*\d+\s*条回复|查看\s*\d+\s*条回复|查看更多评论|查看之前的评论|View .* repl|View more comments)/i;
const hasPending = el => {
  let pending = false;
  el.querySelectorAll('div[role=button],span[role=button]').forEach(b => {
    const t = (b.innerText || '').trim();
    if (t && t.length < 30 && expandRe.test(t)) pending = true;
  });
  return pending;
};

const comments = [...post.querySelectorAll('div[role=article]')]
  .filter(c => c !== post);
const removable = comments.slice(0, Math.max(0, comments.length - keep));

let removed = 0;
for (const c of removable) {
  if (hasPending(c)) continue;      // 下面还有没展开的回复，保留
  if (c.querySelectorAll('div[role=article]').length) continue; // 有子评论，先删子
  c.remove();
  removed++;
}

// 清掉残留的「以…身份评论」整块 composer（头像 + 输入框 + 工具按钮 + 发布）
// 定位：contenteditable 的最近 div[role=table]，正是整个 composer 表格
const editors = [...post.querySelectorAll(
  '[contenteditable="true"][aria-label*="身份评论"],[contenteditable="true"][aria-label*="comment as"]')];
for (let i = 0; i < editors.length - 1; i++) {
  const block = editors[i].closest('div[role="table"]') || editors[i].closest('form');
  if (block && block !== post) {
    block.remove();
    removed++;
  }
}
return removed;
"""

SORT_LABELS = {
    "most_relevant": ("最相关", "MOST_RELEVANT"),
    "newest": ("由新到旧", "NEWEST"),
    "all": ("所有评论", "ALL_COMMENTS"),
}


def post_element_exists(post_id, tab=None):
    tab = tab or get_tab()
    return bool(tab.run_js(JS_FIND_POST % post_id))


def extract_post(post_id, tab=None, retries=5, wait=2.0):
    """从帖子页 DOM 提取正文、作者、时间与互动 aria 标签（带重试）。"""
    tab = tab or get_tab()
    data = {}
    for _ in range(retries):
        try:
            data = json.loads(tab.run_js(JS_POST_TEXT) or "{}")
        except Exception:
            data = {}
        if len(data.get("lines") or []) > 3:
            break
        time.sleep(wait)
    lines = [x.strip() for x in (data.get("lines") or []) if x.strip()]
    return {"lines": lines, "aria": data.get("aria") or []}


SORT_LABELS = {
    "most_relevant": ("最相关", "Most relevant"),
    "newest": ("由新到旧", "Newest"),
    "all": ("所有评论", "All comments"),
}


def _sort_menuitems(tab):
    try:
        return tab.eles('xpath://div[@role="menuitem"]', timeout=1.2) or []
    except Exception:
        return []


def set_sort(kind="most_relevant", tab=None):
    """切换评论排序：most_relevant / newest / all（真实点击，逐个入口尝试）。"""
    tab = tab or get_tab()
    zh, _ = SORT_LABELS.get(kind, SORT_LABELS["most_relevant"])
    labels = ("最相关", "由新到旧", "所有评论", "Most relevant", "Newest")

    for label in labels:
        try:
            entry = tab.ele(
                f'xpath://div[@role="button"][contains(.,"{label}")]', timeout=0.8)
        except Exception:
            entry = None
        if not entry:
            continue
        try:
            entry.click()
        except Exception:
            continue
        time.sleep(random.uniform(1.0, 1.6))

        items = _sort_menuitems(tab)
        if not items:
            continue
        target = None
        for it in items:
            first = (it.text or "").strip().split(chr(10))[0].strip()
            if first == zh:
                target = it
                break
        if not target:
            # 菜单已开但没有目标项，关掉重试下一个入口
            try:
                entry.click()
            except Exception:
                pass
            time.sleep(0.6)
            continue
        try:
            target.click()
        except Exception as exc:
            log.debug("菜单项点击失败：%r", exc)
            return False
        move_mouse_away(tab)
        time.sleep(random.uniform(2.0, 3.0))
        log.info("评论排序切换为 %s", zh)
        return True

    log.debug("排序切换失败：%s", zh)
    return False


def scroll_to_bottom(step=1400, tab=None):
    """滚动评论容器（对话框内），返回滚动后高度。"""
    tab = tab or get_tab()
    return tab.run_js(JS_SCROLLER, timeout=6) or 0


def scroller_state(tab=None):
    tab = tab or get_tab()
    try:
        return json.loads(tab.run_js(JS_SCROLLER_STATE, timeout=6) or "{}")
    except Exception:
        return {}


JS_EXPAND_ONE = r"""
const pats = [
  /^全部\s*\d+\s*条回复$/, /^查看\s*\d+\s*条回复$/,
  /^查看更多评论$/, /^查看之前的评论$/,
  /^See \d+ more repl/i, /^View \d+ more repl/i,
  /^View previous comments$/, /^View more comments$/
];
const all = [...document.querySelectorAll('div[role=button],span[role=button]')]
  .filter(e => {
    const t = (e.innerText || '').trim();
    return t && t.length < 30 && pats.some(p => p.test(t));
  });
if (!all.length) return 0;
const vh = window.innerHeight;
const visible = all.find(e => {
  const r = e.getBoundingClientRect();
  return r.top > 40 && r.bottom < vh - 20;
}) || all[0];
try { visible.scrollIntoView({block: 'center'}); } catch (x) {}
visible.click();
return all.length;
"""


def _hover_xy(tab, ele):
    """按元素中心坐标派发鼠标移动（不等待可交互，避免卡住）。"""
    try:
        rect = ele.rect
        x = int(rect.location[0] + rect.size[0] / 2)
        y = int(rect.location[1] + rect.size[1] / 2)
        tab.run_cdp("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        return True
    except Exception:
        return False


def move_mouse_away(tab=None):
    """把鼠标移到安全元素（标题）上，避免停在头像上触发悬浮卡片。"""
    tab = tab or get_tab()
    for sel in ('xpath://h1', 'xpath://h2', 'xpath://h3'):
        try:
            ele = tab.ele(sel, timeout=0.5)
        except Exception:
            ele = None
        if ele and _hover_xy(tab, ele):
            return True
    return False


def expand_one(pause_min=1.0, pause_max=3.0, tab=None):
    """真实点击一个「全部/查看 N 条回复」，点完随机等待。"""
    tab = tab or get_tab()
    for sel in ('xpath://*[contains(text(),"条回复")]',
                'xpath://*[contains(text(),"查看更多评论")]',
                'xpath://*[contains(text(),"查看之前的评论")]'):
        try:
            ele = tab.ele(sel, timeout=0.4)
        except Exception:
            ele = None
        if not ele:
            continue
        try:
            ele.click(by_js=True)     # JS 点击：不移动鼠标、不等待可交互
        except Exception as exc:
            log.debug("点击失败 %s：%r", sel, exc)
            continue
        move_mouse_away(tab)          # 防止头像 hover 弹出浮层
        time.sleep(random.uniform(pause_min, pause_max))
        return 1
    return 0


def expand_comments(limit=6, pause_min=1.0, pause_max=3.0, tab=None):
    """逐个展开，每个之间随机等待 1-3 秒。"""
    tab = tab or get_tab()
    total = 0
    for _ in range(limit):
        if not expand_one(pause_min, pause_max, tab):
            break
        total += 1
    return total


def prune_comments(keep=40, tab=None):
    """删除已展开完的旧评论节点；带未展开回复的保留（层级安全）。"""
    tab = tab or get_tab()
    try:
        removed = int(tab.run_js(JS_PRUNE_SAFE % keep, timeout=8) or 0)
    except Exception:
        return 0
    if removed:
        log.debug("清理评论节点 %s 个", removed)
    return removed


def parse_post_id(url):
    """从各种 Facebook 链接形态里取出 post_id。

    支持：
      /groups/<gid>/posts/<id>/
      /groups/<gid>/permalink/<id>/
      /groups/<gid>/user/<uid>/post/<id>/     （新版单帖路径）
      /share/p/<id>/  /share/g/<id>/
      /permalink.php?story_fbid=<id>&id=<gid>
      /videos/<id>  /reel/<id>  /watch/?v=<id>
      /photo?fbid=<id>
    带 ?comment_id= 参数时先剥掉查询串。
    """
    u = (url or "").split("?comment_id=")[0]
    for pat in (r"/posts/(\d+)",
                r"/permalink/(\d+)",
                r"/post/(\d+)",
                r"/share/[a-z]/(\d{6,})",
                r"story_fbid=(\d+)",
                r"/(?:videos|reel|watch)/(\d+)",
                r"[?&]v=(\d+)",
                r"fbid=(\d+)"):
        m = re.search(pat, u)
        if m:
            return m.group(1)
    return ""


RE_DATE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日")
RE_REL_TIME = re.compile(r"^(\d+\s*(分钟|小时|天|周|个月|年)前?|刚刚)$")


def parse_post_lines(lines):
    """从帖子 article 的 innerText 提取 author / time / text / 赞 / 评论数。

    结构：群组名 / 作者 / · / 相对时间 / 绝对时间 / 相对时间 / · / 正文 / 赞 / 评论 / 排序按钮 ...
    """
    lines = [(x or "").replace("﻿", "").replace("​", "").strip()
             for x in lines]
    sort_idx = len(lines)
    for i, line in enumerate(lines):
        if line in ("最相关", "Most relevant", "由新到旧", "所有评论",
                    "Newest", "All comments"):
            sort_idx = i
            break
    seg = lines[:sort_idx]

    date_i, ts = None, ""
    for i, line in enumerate(seg):
        if RE_DATE.match(line):
            date_i, ts = i, line
            break
    if date_i is None:
        for i, line in enumerate(seg):
            if RE_REL_TIME.match(line):
                date_i, ts = i, line
                break

    author = ""
    if date_i:
        for j in range(date_i - 1, -1, -1):
            cand = seg[j]
            if cand and cand not in ("·", "关注", "Follow") and not RE_REL_TIME.match(cand):
                author = cand
                break

    body, metrics = [], []
    if date_i is not None:
        for line in seg[date_i + 1:]:
            if line in ("·", "查看翻译", "See translation") or RE_REL_TIME.match(line):
                continue
            if re.fullmatch(r"[\d,]+", line):
                metrics.append(int(line.replace(",", "")))
                continue
            body.append(line)

    # 互动栏紧跟在正文之后：[赞, 评论]
    like = metrics[0] if len(metrics) >= 2 else None
    cmt = metrics[1] if len(metrics) >= 2 else (metrics[0] if metrics else None)
    return {
        "author": author,
        "post_time": ts,
        "text": chr(10).join(body).strip(),
        "like_count": like,
        "comment_count": cmt,
    }


COMMENT_FIELDS = ["post_id", "comment_id", "parent_id", "depth", "author",
                  "text", "time", "like_count"]


def _read_existing_comments(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r.get("comment_id"): r for r in csv.DictReader(f)
                if r.get("comment_id")}


def _read_existing_doc(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_result(posts_dir, post_id, post_url, base, comments):
    """保存帖子 JSON 与评论 CSV（与已有数据合并，不覆盖丢失）。"""
    from .config import COMMENTS_DIR
    cmts_dir = COMMENTS_DIR
    os.makedirs(posts_dir, exist_ok=True)
    os.makedirs(cmts_dir, exist_ok=True)

    doc_path = os.path.join(posts_dir, post_id + ".json")
    csv_path = os.path.join(cmts_dir, post_id + ".csv")

    # 已有帖子记录（来自 feed 整理）作为底稿，本次新值覆盖非空项
    doc = _read_existing_doc(doc_path)
    meta = parse_post_lines(base.get("lines") or [])
    for key, value in meta.items():
        if value not in (None, "", []):
            doc[key] = value
    doc.update({
        "post_id": post_id,
        "post_url": post_url or doc.get("post_url", ""),
        "comment_source": "post_page",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    # 评论合并：保留已有（预览）的，追加新采的
    merged = _read_existing_comments(csv_path)
    for cid, row in comments.items():
        merged[cid] = {
            "post_id": post_id,
            "comment_id": cid,
            "parent_id": row.get("parent_id", ""),
            "depth": row.get("depth", 0),
            "author": row.get("author", ""),
            "text": row.get("text", ""),
            "time": row.get("time", ""),
            "like_count": row.get("like_count", 0),
        }
    doc["comment_collected"] = len(merged)

    with open(doc_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    rows = sorted(merged.values(), key=lambda c: (int(c.get("depth") or 0),
                                                  str(c.get("time") or "")))
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, COMMENT_FIELDS)
        w.writeheader()
        for c in rows:
            w.writerow({k: c.get(k, "") for k in COMMENT_FIELDS})
    log.info("已保存：posts/%s.json（累计 %s 评论 -> comments/%s.csv）",
             post_id, len(rows), post_id)
