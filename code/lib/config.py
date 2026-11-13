"""全局配置：路径常量与可配置参数。"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))       # code/lib
CODE_DIR = os.path.dirname(HERE)                        # code
ROOT = os.path.dirname(CODE_DIR)                        # 项目根

LOG_DIR = os.path.join(ROOT, "logs")
DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
INPUT_FILE = os.path.join(CODE_DIR, "input.csv")

LOGIN_COOKIE = "c_user"

def _load_env(path):
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


_ENV = _load_env(os.path.join(ROOT, ".env"))


def env(name, default=""):
    """优先环境变量，其次 .env，最后默认值。"""
    return os.environ.get(name) or _ENV.get(name) or default


# 本机指纹：全部来自 .env，代码里不留默认路径
PROFILE_ROOT = env("FB_PROFILE_ROOT", os.path.expanduser("~/.pi/agent/browser-profile"))
PROFILE_NAME = env("FB_PROFILE_NAME", "fb")
PROXY = env("FB_PROXY", "")
CHROME = env("FB_CHROME", "")
DEFAULT_PORT = int(env("FB_PORT", "9227"))
