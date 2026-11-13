---
name: facebook-collector
description: 维护 Facebook 群组采集器（GraphQL 监听路线）。改代码、加功能、排查采集问题、理解数据格式时使用。
---

# facebook_collector 维护指南

## 本机指纹

所有本机相关配置（profile 目录、代理、Chrome 路径、端口）都在项目根 `.env`，已被 git 忽略；模板见 `.env.example`。

代码里**禁止**硬编码本机路径，统一走 `lib/config.env()`。

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

## 现有功能

```python
features.collect_group_feed(input_file, start, end, output, port, since,
                            step, pause_min, pause_max, max_idle,
                            max_rounds, prune_every, keep_screens, reload)
```

CLI：`python code/features.py [--since ...] [-i file] [--start N --end M] [--resume] [-q]`

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
