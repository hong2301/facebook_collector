"""浏览器附着工具：统一从 CDP 端口接管已登录的 Chrome。"""
import os
import time
from DrissionPage import Chromium, ChromiumOptions

YT_PORT = 9226
FB_PORT = 9227
TT_PORT = 9228

# 登录态 profile（与 pi 浏览器工具同一套目录）
PROFILE_ROOT = r"C:\Users\jiang\.pi\agent\browser-profile"
PROFILES = {
    YT_PORT: os.path.join(PROFILE_ROOT, "yt"),
    FB_PORT: os.path.join(PROFILE_ROOT, "fb"),
    TT_PORT: os.path.join(PROFILE_ROOT, "tiktok"),
}
PROXY = "http://192.168.31.238:7897"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def attach(port, timeout=20):
    """接管端口上已登录的 Chrome。

    关键：必须同时设置 user_data_path。否则端口空着时 DrissionPage 会拿临时
    profile 拉一个空白浏览器，登录态就丢了。
    """
    co = ChromiumOptions()
    co.set_browser_path(CHROME)
    co.set_user_data_path(PROFILES[port])
    co.set_local_port(port)
    co.set_proxy(PROXY)
    co.set_argument("--no-first-run")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--hide-crash-restore-bubble")
    co.set_argument("--disable-popup-blocking")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--disable-infobars")
    return Chromium(co)


_TAB_CACHE = {}


def work_tab(br, url=None, port=None):
    """复用同一个工作 tab，不新开标签页（用户要求）。

    首次调用时接管端口上已存在的最后一个 tab，之后整轮采集都用它。
    """
    key = port if port is not None else id(br)
    t = _TAB_CACHE.get(key)
    if t is None:
        tabs = [x for x in br.get_tabs() if (x.url or "").startswith("http")]
        if not tabs:
            all_tabs = br.get_tabs()
            t = all_tabs[-1] if all_tabs else br.new_tab()
        else:
            t = tabs[0]
        _TAB_CACHE[key] = t
    if url:
        t.get(url)
    return t


def close_tab(t):
    """不要关闭用户的 tab，只清缓存。"""
    for k, v in list(_TAB_CACHE.items()):
        if v is t:
            _TAB_CACHE.pop(k, None)


def scroll_load(tab, rounds=10, pause=1.5, until_height=None):
    """向下滚动触发懒加载，返回最终滚动高度。"""
    last = 0
    for i in range(rounds):
        tab.run_js("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)
        h = tab.run_js("return document.body.scrollHeight") or 0
        if until_height and h >= until_height:
            break
        if h == last:
            break
        last = h
    return tab.run_js("return document.body.scrollHeight") or 0


def wait_doc(tab, timeout=15):
    """等待页面加载；页面刷新瞬间会抛 ContextLostError，容错重试。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = tab.run_js("return document.readyState")
            if st == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False
