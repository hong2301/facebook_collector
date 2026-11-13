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
