# facebook_collector

Facebook 数据采集工具。分层结构：**功能层 → 原子层 → 实现层**。

## 怎么读这个项目

按这个顺序看，从外到内：

| 顺序 | 看什么 | 能知道什么 |
|---|---|---|
| 1 | `doc/INDEX.md` | 每个文件干什么、数据怎么流、新增代码放哪 |
| — | `SKILL.md` | 给 AI/维护者：约定、禁区、验证清单（不需要时忽略） |
| 2 | `code/features.py` | 业务入口：有哪些功能，参数是什么 |
| 3 | `code/atoms.py` | 原子能力：开端口、查登录、采一个主页 |
| 4 | `code/lib/` | 具体实现：监听、滚动、日志、会话 |
| 5 | `doc/` | 接口结构、字段定义、URL 参数、踩过的坑 |

只想跑起来：直接看下面「用法」。
想改逻辑：先看 `features.py` 有没有现成的组合，再动 `atoms.py`，最后才进 `lib/`。

## 结构

```
facebook_collector/
├── README.md           给人看：怎么用、怎么读
├── SKILL.md            给 AI 看：维护约定、禁区、验证清单
├── code/input.csv           输入清单（CSV，url 列）
├── code/
│   ├── atoms.py        原子层（打开端口 / 检测登录 / 采集主页 / 采集帖子）
│   ├── features.py     功能层（原子组合 + 功能参数 + CLI 入口）
│   └── lib/            实现层
│       ├── config.py     路径常量
│       ├── logger.py     双写日志（控制台 + logs/*.log）
│       ├── browser.py    Chrome CDP 接管
│       ├── session.py    会话状态（端口 / 浏览器 / 标签页）
│       ├── auth.py       登录检测
│       ├── listener.py   GraphQL 监听（GraphQLRecorder）
│       ├── scroll.py     主页滚动 + DOM 清理
│       ├── post.py       帖子页：正文提取 / 评论排序 / 展开 / 清理
│       ├── comments.py   评论解析（顶层 + 回复）
│       └── utils.py      输入清单 / 切片 / 停顿
├── data/
│   ├── raw/            所有接口原始响应 + index.csv（type 区分 feed/评论）
│   ├── posts/          每帖一个 JSON
│   └── comments/       每帖一个评论 CSV
├── doc/               细分文档（索引 / 接口 / 字段 / URL 参数 / 已知问题）
└── logs/              运行日志
```

## 用法

```bash
python code/features.py                   # 按默认参数采集
python code/features.py --since 2025-01-01
python code/features.py -i other.txt --start 0 --end 1
python code/features.py -q                # 静默
```

## 分层约定

| 层 | 文件 | 放什么 |
|---|---|---|
| 功能层 | `features.py` | 组合原子动作 + 该功能的参数 + CLI |
| 原子层 | `atoms.py` | 最小可执行单元：开端口 / 查登录 / 采集一个主页 |
| 实现层 | `lib/*.py` | 具体实现，不含流程 |

新增功能时：原子能力放 `lib/` + `atoms.py` 加一个函数；业务流程放 `features.py`，参数跟功能走。

## 采集流程

```
open_port → use_tab → check_login
        → start_listen → open_url → scroll_until → stop_listen
```

- **监听常开**：滚动前启动、结束后停止，独立线程消费，中途手动滚动也不会漏
- **停止条件**：监听数据里出现早于 `--since` 的帖子 / 连续 `--max-idle` 轮无新内容
- **DOM 清理**：每 `prune_every` 轮删掉视口上方 `keep_screens` 屏以外的帖子节点，防止长列表卡顿

## 配置（本机指纹）

复制 `.env.example` 为 `.env` 并按本机情况填写，`.env` 不进版本库：

```
FB_PROFILE_ROOT=C:\Users\<you>\.pi\agent\browser-profile
FB_PROFILE_NAME=fb
FB_PROXY=http://127.0.0.1:7897
FB_CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
FB_PORT=9227
```

代码里不含本机路径，全部通过 `lib/config.env()` 读取。

## 运行前提

- Chrome 以调试端口 `9227` 运行且已登录 Facebook
- profile：由 `.env` 的 `FB_PROFILE_ROOT` / `FB_PROFILE_NAME` 决定
- 依赖：`DrissionPage`、Python 3.14
