# 项目索引

按「想找什么 → 去哪里看」组织。新增文件请同步更新此表。

## 1. 目录职责

| 目录 | 放什么 | 不放什么 |
|---|---|---|
| `code/` | 可执行代码 + 输入清单 `input.csv` | 数据、日志 |
| `code/lib/` | 实现层，一个文件一个领域 | 业务流程编排 |
| `data/raw/` | 接口原始响应（运行时产生，已 gitignore） | 整理后的交付文件 |
| `.env` | 本机指纹（profile / 代理 / Chrome / 端口），已 gitignore | 提交 |
| `doc/` | 设计与契约文档 | 代码 |
| `logs/` | 运行日志（已 gitignore） | — |

## 2. 代码文件索引

### 入口与索引层

| 文件 | 职责 | 关键内容 |
|---|---|---|
| `code/atoms.py` | **原子层**（最小可执行单元） | 小组：`open_port` / `check_login` / `collect_group_posts`<br>帖子：`collect_post(post_url, output, sort, max_comments, ...)` |
| `code/features.py` | **功能层**（原子组合 + 功能参数 + CLI） | `collect_group_feed(...)`（主页）<br>`collect_post_url(...)`（单帖+评论）<br>`collect_posts(...)`（批量帖子） |

### 实现层 `code/lib/`

| 文件 | 职责 | 关键内容 |
|---|---|---|
| `code/lib/config.py` | 路径常量 + `.env` 读取 | `ROOT` / `RAW_DIR` / `LOG_DIR` / `INPUT_FILE` / `LOGIN_COOKIE`；`env()` / `PROFILE_ROOT` / `PROXY` / `CHROME` / `DEFAULT_PORT` |
| `code/lib/logger.py` | 双写日志 | `get_logger()` / `setup()`，控制台 + `logs/*.log` |
| `code/lib/browser.py` | Chrome CDP 接管 | `attach(port)` / `wait_doc()` / `FB_PORT` / profile 路径 |
| `code/lib/session.py` | 会话状态 | `open_port` / `pick_tab` / `get_tab` / `is_connected`，全局状态存 `_state` |
| `code/lib/auth.py` | 登录检测 | `is_logged_in(tab)`，只读 `c_user` cookie |
| `code/lib/listener.py` | GraphQL 监听 | `GraphQLRecorder`（后台线程落盘）、`parse_body_tree()`（JSONL 合并）、`RAW_DIR` |
| `code/lib/scroll.py` | 主页滚动与 DOM 清理 | `scroll_once` / `scroll_until` / `prune_dom` / `at_bottom` / `page_state` |
| `code/lib/post.py` | 帖子页：数据提取 / 排序 / 展开 / 清理 | `extract_post` / `set_sort` / `scroll_to_bottom` / `expand_comments` / `prune_comments` / `save_result` |
| `code/lib/comments.py` | 评论解析 | `parse_response`（顶层 + Depth1/Depth2）、`parse_comment_node` |
| `code/lib/__init__.py` | 包说明（各模块一行职责） | — |
| `code/lib/utils.py` | 通用工具 | `read_input` / `select_groups` / `normalize_url` / `pick_pause` |

## 3. 文档索引

| 文档 | 内容 |
|---|---|
| `README.md` | 给人看：怎么读、怎么用、分层约定 |
| `SKILL.md` | 给 AI 看：维护约定、禁区、验证清单、问题定位 |
| `doc/INDEX.md` | 本文件：文件职责、数据流、新增代码放哪 |
| `doc/api-notes.md` | GraphQL 接口：doc_id、variables、JSONL 合并规则、字段路径 |
| `doc/data-dictionary.md` | 帖子 / 评论 / 索引的字段定义与计数口径 |
| `doc/url-parameters.md` | `sorting_setting` 三个取值及影响 |
| `doc/known-issues.md` | 已知问题：排序、JSONL、零值、标签页残留、滚动节奏 |

## 4. 数据流

```
code/input.csv（一行一个小组链接）
   │
   ▼
features.collect_group_feed(input_file, start, end, output, port, ...)
   │  read_input → 按 start/end 切片
   ├─ atoms.open_port(port)                连接/拉起 Chrome
   ├─ atoms.check_login()                  只读 cookie
   └─ for url in urls:
        atoms.collect_group_posts(url, output, **采集参数, reload=True)
          ├─ reload=True：打开链接（CHRONOLOGICAL）
          │  reload=False：沿用当前页面位置（--resume）
          ├─ 启动 GraphQL 监听（常开，独立线程）
          ├─ 循环 scroll_once + 定期 prune_dom
          │    停止：出现早于 since 的帖子 / 连续 max_idle 轮无新内容
          └─ 停止监听，返回 rounds/reason/captured
   │
   ▼
data/raw/<seq>_<ts>_<doc_id>.jsonl  +  data/raw/index.csv
```

## 5. 常用命令

```bash
python code/features.py                        # 默认参数采集
python code/features.py --since 2025-01-01
python code/features.py -i other.txt --start 0 --end 1
python code/features.py group -q               # 静默
python code/features.py group --resume         # 接续：不重新加载

# 采集单个帖子 + 完整评论
python code/features.py post <帖子链接> --sort all

# 批量采集帖子（读 code/input_posts.csv 或直接给链接）
python code/features.py posts
python code/features.py posts <url1> <url2> --max-comments 100
python code/features.py post <帖子链接> --sort all

# 批量采集帖子（读 code/input_posts.csv 或直接给链接）
python code/features.py posts
python code/features.py posts <url1> <url2> --max-comments 100 --max-comments 100   --scroll-pause-min 1.5 --scroll-pause-max 3 --pause-min 1.5 --pause-max 3

# 或在代码里组合原子动作
python -c "import sys; sys.path.insert(0,'code'); import index; atoms.open_port(9227); atoms.check_login()"
```

## 6. 新增代码怎么放

| 要做的事 | 放哪 |
|---|---|
| 新的原子能力（如「读取某接口」） | `lib/` 实现 + `atoms.py` 新增一个原子函数 |
| 新的业务流程（如「采集评论」） | `features.py` 新增函数，组合 `index` 的原子动作 |
| 新参数 | 功能函数签名 + `features.main()` 的 argparse（属于该功能自己） |
| 新文档 | `doc/`，并更新本文件第 3 节 |

## 7. 帖子采集输出

```
data/posts/<post_id>.json          帖子：author / post_time / text / like_count / comment_count
data/posts/comments/<post_id>.csv  评论：depth 0-2、parent_id、作者、正文、时间、点赞
```

同名 `post_id` 配对。评论排序必须用 `all`（最相关只有 25 条，所有评论 35 条）。

## 8. 当前数据（2025-01-01 ~ 2026-11-12）

| 项 | 值 |
|---|---|
| 响应文件 | 585 |
| 去重帖子 | 1,746 |
| 正文完整 | 1746 / 1746 |
| 点赞合计 | 8,311（均值 4.76，最高 279） |
| 评论合计 | 22,798（均值 13.06，中位 7，最高 445） |
| 分享合计 | 255 |
| 零评论帖 | 367（21%） |

2025 年 1,224 帖 / 2026 年 520 帖 / 2024-12 边界 2 帖。
