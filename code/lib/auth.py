"""登录状态检测。"""

from .config import LOGIN_COOKIE
from .session import get_tab


def is_logged_in(tab=None):
    """只读 cookie 判断登录态，不导航页面。返回 (bool, 说明)。"""
    tab = tab or get_tab()
    try:
        cookies = tab.cookies(all_domains=True) or []
    except Exception as exc:
        return False, repr(exc)
    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    if LOGIN_COOKIE not in names:
        return False, f"{LOGIN_COOKIE} cookie 不存在"
    if "/login" in (tab.url or ""):
        return False, "页面被重定向到登录页"
    return True, "ok"
