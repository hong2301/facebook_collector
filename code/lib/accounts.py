"""账号清单：读取 accounts.json（项目根，已 gitignore）。"""

import json
import os

from .config import ROOT

ACCOUNTS_FILE = os.path.join(ROOT, "accounts.json")


def load_accounts(path=None):
    """返回账号列表；文件不存在时返回空列表。"""
    path = path or ACCOUNTS_FILE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return [a for a in data if isinstance(a, dict)]


def find_account(name, path=None):
    """按 name 或 user_id 查找账号。"""
    for acc in load_accounts(path):
        if name in (acc.get("name"), acc.get("user_id")):
            return acc
    return None
