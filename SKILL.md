---
name: facebook-collector
description: 维护 Facebook 群组采集器（GraphQL 监听路线）。改代码、加功能、排查采集问题、理解数据格式时使用。
---

# facebook_collector 维护指南

## 本机指纹

所有本机相关配置（profile 目录、代理、Chrome 路径、端口）都在项目根 `.env`，已被 git 忽略；模板见 `.env.example`。

代码里**禁止**硬编码本机路径，统一走 `lib/config.env()`。

## 账号

`accounts.json`（项目根，已 gitignore）存账号：`user_id` / `password` / `totp_secret` / `port` / `profile`。

- 验证码本地算：`lib.totp.now(secret)`，与 2fa.fan 结果一致，不必依赖外部网站
- 登录：`features.py login [name]`，已登录的 profile 会跳过，不会登出
- 每个账号必须使用独立 `port` + `profile`，避免登录态互相覆盖
- 严禁把 `accounts.json` 提交到仓库或贴进任何会外传的地方

## 项目性质

采集 Facebook 公开群组的帖子与互动数据。**只做被动监听**：不构造请求、不伪造参数、不改请求频率，只旁听页面自己发出的 `/api/graphql` 响应并落盘。

真实账号在跑，任何提高请求频率、批量重放接口的改动都视为破坏性变更。

## 三层结构（改代码前先定位层级）

```
code/
├── atoms.py      原子层：最小可执行单元
├── features.py   功能层：原子组合 + 功能自己的参数 + CLI
└── lib/          实现层：具体实现，不含流程
```

| 改动类型 | 位置 |
|---|---|
| 新增原子能力（如「读取评论分页」） | `lib/` 实现 + `atoms.py` 加函数 |
| 新增业务流程（如「采集评论」） | `features.py` 加函数，参数跟着该功能走 |
| 新参数 | 功能函数签名 + 该功能的 argparse，**不要**塞进全局配置 |
| 新文档 | `doc/`，并更新 `doc/INDEX.md` |

硬性约定：

- 原子层只放最小动作，当前只有 `open_port` / `check_login` / `collect_group_posts`
- 功能层负责参数与遍历，`main.py` 已删除，不要重新引入
- `lib/config.py` 只放路径常量，不放业务参数

## 现有原子

| 函数 | 说明 |
|---|---|
| `atoms.open_port(port)` | 接管 CDP 端口，未启动则按 profile 拉起（保留登录态） |
| `atoms.check_login()` | 只读 `c_user` cookie，**不导航页面** |
| `atoms.collect_group_posts(url, output, since, ..., reload=True)` | 打开链接（或沿用当前页）→ 常开监听 → 滚动 → 停止 → 返回统计 |
| `atoms.collect_post(post_url, output, sort, max_comments, pause_min, pause_max, scroll_pause_min, scroll_pause_max, max_idle, max_rounds, prune_keep)` | 帖子页 → 提取正文 → 切排序 → 滚动 + 展开回复 → 停止 → 存 JSON + CSV |

## 现有功能

```python
features.collect_group_feed(input_file, start, end, output, port, since,
                            step, pause_min, pause_max, max_idle,
                            max_rounds, prune_every, keep_screens, reload)
```

```python
features.collect_post_url(post_url, output, sort="all", max_comments=0,
                          pause_min=1.0, pause_max=3.0,
                          scroll_pause_min=1.0, scroll_pause_max=3.0,
                          max_idle=6, max_rounds=500, prune_keep=40)
```

```python
features.collect_posts(urls=None, input_file="code/input_posts.csv", start=0, end=0,
                       output="data/posts", sort="all", max_comments=0, ...)
```

```python
features.build_posts_from_raw(raw_dir="data/raw", output="data/posts")  # 零请求整理
features.plan_missing_posts(posts_dir="data/posts", out_file="code/input_posts.csv")
```

CLI：

```
python code/features.py group [...]          # 小组主页
python code/features.py post <url> [...]     # 单个帖子
python code/features.py posts [url ...]      # 批量帖子
python code/features.py build                # raw → 帖子 JSON + 评论 CSV
python code/features.py plan                 # 生成待补采清单
```

`--resume`：`reload=False`，沿用当前页面位置继续滚，不重新加载。用于中断后续采。

## 采集流程（不要打乱顺序）

```
open_port → check_login
  → collect_group_posts:
      tab.get(url)（URL 必须带 sorting_setting=CHRONOLOGICAL）
      tab.listen.start("graphql")
      GraphQLRecorder 后台线程落盘
      while: scroll_once → 判断 oldest_seen < since / 连续 max_idle 轮无新增
      stop_listen
```

监听必须在滚动**之前**启动、之后停止，且独立线程消费。禁止「滚一次开一次监听」，否则手动滚动或连续触发会漏响应。

## 停止条件

| 条件 | reason |
|---|---|
| 监听数据出现早于 `since` 的帖子 | `reached_since` |
| 连续 `max_idle` 轮到底且高度不增长 | `no_new_content` |
| 达到 `max_rounds` | `max_rounds` |

## 帖子采集要点

| 项 | 结论 |
|---|---|
| 排序 | **必须选 `all`（所有评论）**；默认「最相关」只给精选，本条帖子 25 条 vs 35 条 |
| 排序切换 | 必须用真实鼠标点击（JS `click()` 打不开菜单）；菜单项按**首行文本**匹配，副标题也含「所有评论」 |
| 展开回复 | 逐个点「全部N条回复/查看N条回复/查看更多评论」，每个之间随机等 `pause_min~pause_max` |
| 滚动等待 | 独立参数 `scroll_pause_min~scroll_pause_max`，默认 1-3 秒 |
| 评论接口 | `CommentsListComponentsPaginationQuery`（顶层）+ `Depth1/Depth2CommentsListPaginationQuery`（回复） |
| 层级 | 最多 3 级（depth 0/1/2），三级下不再有四级 |
| 停止 | 达到 `max_comments` / **连续 `max_idle`（默认 5）轮无新增评论** / `max_rounds` |

## DOM 清理（评论页）

- 帖子本体（最长且 >400 字符的 article）**永不删**
- 只删「自身及子孙没有待展开按钮」的评论节点，有子评论先跳过
- composer 整块 = `contenteditable` 的最近 `div[role="table"]`，连头像/工具/发布一起删，保留最后一块

## 数据契约

```
data/raw/<seq>_<YYYYmmdd-HHMMSS>_<doc_id>.jsonl   原始响应，JSONL，不改写
data/raw/index.csv                                每行一个响应
```

`index.csv` 列：`seq,ts,group,doc_id,resp_bytes,n_posts,post_ids,min_ts,max_ts,end_cursor_len,has_next,friendly_name,file`

- `group` = 该响应来自哪个 input 链接（必填，用于溯源）
- `min_ts/max_ts` = 本次响应内帖子的最早/最晚发布时间（unix 秒），驱动停止判断
- 非 feed 响应（`post_ids` 为空）直接丢弃，不落盘

响应是 **JSONL**，解析必须按行 + 按 `path` 合并（见 `lib/listener.parse_body_tree`）。合并时：

- 路径里的整数索引 → 该层必须是 list
- 末层两个 dict → 必须 `update` 合并，不能整体赋值（`page_info` 会覆盖掉 `edges`）

## 禁止事项

| 禁止 | 原因 |
|---|---|
| 直接打印（`print`） | 全部走 `lib/logger`，控制台 + `logs/*.log` 双写 |
| 用 `scrollTo(0, scrollHeight)` 一步到底 | 会跳过中间页，漏请求 |
| 重放/构造 GraphQL 请求 | cursor 必须来自上一页，且高频请求有封号风险 |
| 关掉或刷新工作标签页 | 采集结束后标签页保留，便于事后重提取 |
| 在 `collect_group_posts` 外启停监听 | 会漏掉手动滚动产生的响应 |
| 手动 `kill` 采集进程前不确认 | 会丢掉正在跑的批次（接续要用 `--resume`） |
| 用真实鼠标点击展开按钮 | 会悬停在头像上弹浮层，且可能阻塞；用 `by_js=True` |

## 验证清单

```bash
cd facebook_collector
python -m py_compile code/atoms.py code/features.py code/lib/*.py
python code/features.py --help
python code/features.py --since 2026-11-01 --max-rounds 5   # 短跑验证
```

短跑要检查：`data/raw/index.csv` 的 `group` 有值、`n_posts=3`、日志出现「采集结束」。

## 常见问题定位

| 现象 | 位置 |
|---|---|
| 采不到新帖 | 检查 URL 是否带 `sorting_setting=CHRONOLOGICAL`（默认「最相关」会漏采） |
| 数据量大后页面卡 | `lib/scroll.py`：`prune_every` / `keep_screens` 调小 |
| 连接端口超时 | 标签页残留过多，用 CDP `/json/close/<id>` 清理 |
| 登录检查失败 | 9227 端口未登录，或页面被重定向到 `/login` |
| 停止过早 | `min_ts` 判断过于激进，或 `since` 设置得太近 |
| 评论比页面少 | 排序不是 `all`，或展开按钮没点到（DOM 里 `NoRectError` 说明元素不可见） |
| 排序切错 | 菜单项用了 `contains` 匹配，副标题也含「所有评论」→ 点到「由新到旧」 |
