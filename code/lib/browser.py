"""浏览器附着：从 CDP 端口接管已登录的 Chrome。

本机相关路径（profile 目录、代理、Chrome 路径）全部来自 .env，
见 .env.example。
"""

import os
import time

from DrissionPage import Chromium, ChromiumOptions

from . import config

FB_PORT = config.DEFAULT_PORT


def profile_path(name=None):
    """登录态 profile 目录：PROFILE_ROOT/<name>。"""
    return os.path.join(config.PROFILE_ROOT, name or config.PROFILE_NAME)


def attach(port, timeout=20):
    """接管端口上已登录的 Chrome。

    关键：必须同时设置 user_data_path。否则端口空着时 DrissionPage 会拿临时
    profile 拉一个空白浏览器，登录态就丢了。
    """
    co = ChromiumOptions()
    if config.CHROME:
        co.set_browser_path(config.CHROME)
    co.set_user_data_path(profile_path())
    co.set_local_port(port)
    if config.PROXY:
        co.set_proxy(config.PROXY)
    co.set_argument("--no-first-run")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--hide-crash-restore-bubble")
    co.set_argument("--disable-popup-blocking")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--disable-infobars")
    return Chromium(co)


def wait_doc(tab, timeout=15):
    """等待页面加载完成；刷新瞬间会抛异常，容错重试。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if tab.run_js("return document.readyState") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False
