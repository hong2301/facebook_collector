# 数据结构与字段定义

原始响应在 `data/raw/`。整理成交付文件时，以 `post_id` 为唯一键，`posts/<post_id>.json` 与 `comments/<post_id>.csv` 同名配对。

## 1. 帖子交付形态 `posts/<post_id>.json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `post_id` | string | Facebook 帖子 ID（纯数字），全局唯一 |
| `group_id` | string | 群组 ID，固定 `2201697719848708` |
| `post_url` | string | 帖子永久链接 |
| `author` | string | 发帖人昵称（匿名互动者 / Anonymous participant 会原样保留） |
| `post_time` | string | `YYYY-MM-DD HH:MM`，浏览器本地时区（UTC+8） |
| `text` | string | 正文全文，已展开、已清理按钮噪声 |
| `media_type` | string | 固定 `group` |
| `source` | string | 数据来源，接口路径为 `api` |
| `fetched_at` | string | 采集时间 |
| `like_count` | int \| null | 点赞（心情）总数 |
| `comment_count` | int \| null | 评论总数（FB 互动栏，通常不含子回复） |
| `share_count` | int \| null | 分享数，FB 为 0 时界面不显示 |
| `media.images` | string[] | 图片 CDN 链接（scontent，带签名参数，会过期） |
| `media.videos` | string[] | video 标签直链 |
| `media.video_hrefs` | string[] | 视频页链接 |
| `media.links` | string[] | 正文里的外链（已解 l.facebook.com 跳转） |
| `has_image` / `has_video` | bool | 媒体标记 |

> 图片链接是 CDN 临时地址，几小时后失效；需要留图要在采集当时下载。

## 2. 评论交付形态 `comments/<post_id>.csv`

| 列 | 说明 |
|---|---|
| `post_id` | 配对键 |
| `post_url` | 帖子链接（冗余，便于单文件使用） |
| `comment_id` | FB 评论 ID（接口字段 `legacy_fbid`） |
| `parent_comment_id` | 父评论 ID，顶级为空；接口路径的回复会填 |
| `depth` | 0 = 顶级，≥1 = 回复 |
| `author` | 评论者昵称 |
| `comment_text` | 评论正文 |
| `comment_time` | `YYYY-MM-DD HH:MM` |
| `like_count` | 评论自身点赞数（`top_reactions` 汇总） |
| `reply_count` | 该评论的回复数 |

**注意**：这里只存 Feed 里带出的预览评论（每帖 0–2 条）。评论总数见帖子的 `comment_count`，全量评论需另走评论分页接口。

## 3. 索引形态 `index.csv`

| 列 | 说明 |
|---|---|
| `post_id` `post_time` `author` | 同上 |
| `like_count` `comment_count` `share_count` | 同上 |
| `has_image` `has_video` | 0/1 |
| `text_len` | 正文字符数 |
| `post_url` | 链接 |

## 4. 接口原始索引 `data/raw/index.csv`

| 列 | 说明 |
|---|---|
| `seq` | 递增序号 |
| `ts` | 落盘时间 |
| `doc_id` | GraphQL 操作 ID（feed 为 `28808848798817508`） |
| `resp_bytes` | 原始响应字节数 |
| `n_posts` | 本次响应解析出的帖子数 |
| `post_ids` | 帖子 ID 列表，`;` 分隔 |
| `end_cursor_len` | 下一页游标长度 |
| `has_next` | 是否还有下一页 |
| `friendly_name` | 操作名，如 `GroupsCometFeedRegularStoriesPaginationQuery` |
| `file` | 原始 JSONL 文件名 |

## 5. 计数口径

| 指标 | 口径 |
|---|---|
| 点赞 | 所有 reaction 之和（赞、爱心、笑等），不是单一「赞」 |
| 评论 | FB 互动栏「N 条评论」，通常**不含**子回复 |
| 分享 | FB 互动栏第三个数字，为 0 时界面不显示 |
| 零值 | 帖子有互动按钮但无数字 = 0；完全没有按钮 = null |
