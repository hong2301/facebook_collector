# 群组 URL 参数

群组页可用的查询参数，写在 `-i/--input` 的链接里：

```
https://www.facebook.com/groups/<group_id>/?sorting_setting=<VALUE>
```

## sorting_setting — 帖子排序

| 值 | 界面显示 | 含义 | 采集影响 |
|---|---|---|---|
| `TOP_POSTS` | 最相关 | 按互动/相关度排序（默认） | **不可用**：帖子不按时间推进，滚动深了也拿不到早期帖子，实测 2025 年整年仅采到 18 帖 |
| `RECENT_ACTIVITY` | 近期动态 | 按最近活动（发帖或新评论）排序 | 有评论的老帖会被顶上来，时间乱序，会重复访问同一帖 |
| `CHRONOLOGICAL` | 最新动态 | 严格按发帖时间倒序 | **推荐**：时间单调递减，滚到 `--since` 即可安全停止 |

## 其他常见参数

| 参数 | 说明 |
|---|---|
| `multi_permalinks=<post_id>` | 定位到某条帖子 |
| `ref=bookmarks` | 来源标记，不影响内容 |
| `__cft__[0]` | FB 内部签名，抓 URL 时要剔除 |

## 使用建议

- 采集一律用 `CHRONOLOGICAL`，这是停止条件（滚到 `--since` 前即停）成立的前提。
- `RECENT_ACTIVITY` 只会出现在人工浏览场景，不适合批量采集。
- 不要把 `sorting_setting` 写死在代码里，按任务在 input 中指定。

## 示例

```bash
python code/main.py -i "https://www.facebook.com/groups/2201697719848708/?sorting_setting=CHRONOLOGICAL"
```
