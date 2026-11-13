"""Facebook 登录：账号密码 + TOTP 两步验证。

只在需要新增账号时用；已有登录态的 profile 不要重复登录。

用法：
    from lib.login import login
    login({"user_id": "...", "password": "...", "totp_secret": "..."},
          port=9229, profile="fb2")

限制：遇到人机验证、短信验证码、异地登录确认时无法自动完成，
需要人工在该标签页操作后手动确认。
"""

import time

from . import browser
from .logger import get_logger
from .totp import now as totp_now

log = get_logger("collector")

LOGIN_URL = "https://www.facebook.com/login"
SELECTORS = {
    "email": ('xpath://input[@name="email"]', 'xpath://input[@id="email"]'),
    "pass": ('xpath://input[@name="pass"]', 'xpath://input[@id="pass"]'),
    "submit": ('xpath://button[@name="login"]',
               'xpath://button[@type="submit"]',
               'xpath://div[@role="button"][.//span[text()="登录"]]',
               'xpath://div[@role="button"][.//span[text()="Log in"]]'),
}


def _fill(tab, keys, value):
    for sel in SELECTORS[keys]:
        try:
            ele = tab.ele(sel, timeout=1.5)
        except Exception:
            ele = None
        if ele:
            ele.clear(by_js=True)
            ele.input(value, by_js=True)
            return True
    return False


def _click(tab, keys):
    for sel in SELECTORS[keys]:
        try:
            ele = tab.ele(sel, timeout=1.5)
        except Exception:
            ele = None
        if ele:
            ele.click(by_js=True)
            return True
    return False


def _needs_2fa(tab):
    for sel in ('xpath://input[@name="approvals_code"]',
                'xpath://input[@autocomplete="one-time-code"]',
                'xpath://input[contains(@aria-label,"code")]'):
        try:
            if tab.ele(sel, timeout=0.8):
                return True
        except Exception:
            pass
    return False


def _fill_2fa(tab, secret):
    code = totp_now(secret)
    for sel in ('xpath://input[@name="approvals_code"]',
                'xpath://input[@autocomplete="one-time-code"]',
                'xpath://input[contains(@aria-label,"code")]'):
        try:
            ele = tab.ele(sel, timeout=1.0)
        except Exception:
            ele = None
        if ele:
            ele.input(code, by_js=True)
            log.info("已填 2FA 验证码")
            break
    _click(tab, "submit")
    time.sleep(4)


def logged_in(tab):
    try:
        cookies = tab.cookies(all_domains=True) or []
    except Exception:
        return False
    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    return "c_user" in names and "/login" not in (tab.url or "")


def login(account, port=9227, profile=None, wait=6):
    """登录一个账号，返回是否成功。

    Args:
        account: dict，含 user_id / password / totp_secret
        port:    该账号使用的调试端口
        profile: profile 子目录名（不同账号必须不同）
    """
    user = account.get("user_id") or account.get("email")
    pwd = account.get("password")
    secret = account.get("totp_secret")
    if not (user and pwd):
        log.error("账号信息不完整")
        return False

    br = browser.attach(port, profile=profile, timeout=12)
    tab = br.new_tab()
    tab.get(LOGIN_URL)
    browser.wait_doc(tab, 25)
    time.sleep(3)

    if logged_in(tab):
        log.info("端口 %s 已是登录状态，无需重复登录", port)
        return True

    if not _fill(tab, "email", user) or not _fill(tab, "pass", pwd):
        log.error("找不到账号/密码输入框")
        return False
    time.sleep(0.8)
    _click(tab, "submit")
    log.info("已提交登录表单，等待跳转")
    time.sleep(wait)
    browser.wait_doc(tab, 20)

    if _needs_2fa(tab):
        if not secret:
            log.error("需要 2FA 但没有 totp_secret")
            return False
        _fill_2fa(tab, secret)
        time.sleep(wait)

    for _ in range(6):
        if logged_in(tab):
            log.info("登录成功：%s（端口 %s，profile %s）", user, port, profile)
            return True
        time.sleep(3)

    log.error("登录未完成，可能触发了人机验证/短信验证，需要人工处理")
    log.error("当前页面：%s", (tab.url or "")[:100])
    return False
