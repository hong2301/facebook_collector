# GraphQL 接口结构（供监听与二次开发）

> 只做被动监听，不主动发请求。监听器 `code/api_listen.py`。

## 1. 端点

```
POST https://www.facebook.com/api/graphql/
Content-Type: application/x-www-form-urlencoded
```

必需参数：`fb_dtsg`、`lsd`、`jazoest`、`doc_id`、`variables`，其余为客户端指纹（`__req`/`__hsi`/`__dyn` 等）。

## 2. 群组 feed 操作

| 项 | 值 |
|---|---|
| `doc_id` | `28808848798817508` |
| `fb_api_req_friendly_name` | `GroupsCometFeedRegularStoriesPaginationQuery` |
| 每次返回 | 3 帖 |
| 单次响应 | 190–450 KB |

`variables` 关键项：

```json
{
  "count": 3,
  "cursor": "<上一页 end_cursor>",
  "feedLocation": "GROUP",
  "feedType": "DISCUSSION",
  "sortingSetting": "CHRONOLOGICAL",
  "id": "2201697719848708",
  "renderLocation": "group"
}
```

## 3. 响应是 JSONL，不是单个 JSON

一个响应由 4 行组成，每行独立合法 JSON：

| 行 | 内容 |
|---|---|
| 0 | `{"data":{"node":{...}}}` 主数据，`group_feed` 通常为 `null` |
| 1 | deferred：`path=["node","group_feed","edges",1]`，即第 2 帖 |
| 2 | deferred：`path=["node","group_feed","edges",2]`，即第 3 帖 |
| 3 | deferred：`path=["node","group_feed"]`，含 `page_info.end_cursor` |

**必须按 `path` 合并到同一棵树**，否则 `edges` 永远只看到第 1 帖、`page_info` 会覆盖 `edges`。

合并规则（`api_listen.parse_body_tree`）：

- `path` 中的整数索引 → 该层必须是 list
- 末层已是 dict 且新值也是 dict → 合并（update），不能整体替换
- 否则赋值

## 4. 帖子字段路径

| 数据 | 路径 |
|---|---|
| 帖子 ID | `edges[].node.post_id` |
| 发布时间 | `edges[].node.creation_time`（unix 秒） |
| 永久链接 | `edges[].node.permalink_url` |
| 正文 | `edges[].node.comet_sections.content.story.message.text` |
| 作者 | `edges[].node.comet_sections.content.story.actors[0].name` |
| 附件 | `edges[].node.attachments[].media.__typename`（`Image`/`Video`） |
| 点赞 | `reaction_count.count`（深层，用递归查找） |
| 评论总数 | `comment_rendering_instance.comments.total_count` |
| 分享数 | `share_count.count` |
| 预览评论 | `interesting_top_level_comments[]` |

## 5. 预览评论结构

```
interesting_top_level_comments[]:
  comment.legacy_fbid                    评论 ID
  comment.body.text                      正文
  comment.author.name                     作者
  comment.created_time                    unix
  comment.depth                           层级
  comment.feedback.top_reactions.edges[].reaction_count   评论点赞
  comment.feedback.total_reply_count      回复数
  relevant_contextual_replies.nodes[]     带出的回复
```

每条帖子带 0–2 条预览评论。评论总数 ≤ 2 时，预览即全量。

## 6. 翻页

`page_info.end_cursor`（在最后一行 deferred 里）+ `has_next_page`。cursor 是 protobuf 的 base64，**不能凭空构造**，必须来自上一次响应。

## 7. 注意事项

- `doc_id` 会随 FB 前端版本变化，脚本不要硬编码成唯一入口，优先从监听到的请求里取。
- 响应里 `prefetch_uris_v2`（头像 CDN）占大部分体积，可丢。
- 正文在接口里为纯文本，无「查看更多」折叠问题，也无日期前缀。
