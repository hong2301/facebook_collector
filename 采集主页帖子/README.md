# Facebook 帖子采集工具

基于 [DrissionPage](https://github.com/g1879/DrissionPage) 的 Facebook 主页帖子采集脚本，需要人工辅助登录和目标页面导航。

## 快速开始

### 1. 启动浏览器（带调试端口）

以 Chrome 为例，先**完全关闭**所有 Chrome 窗口，然后用以下命令启动：

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=2727
```

> `2727` 与 `main.py` 中的 `tabPort` 对应，可自定义但需保持一致。

### 2. 登录 Facebook

在上一步打开的浏览器中，手动访问 `facebook.com` 并登录你的账号。

### 3. 加载目标主页

登录后，在同一个浏览器中打开你要采集的 Facebook 主页，例如：

```
https://www.facebook.com/huawei/
https://www.facebook.com/CAS.science/
https://www.facebook.com/ByteDancer
```

> 页面加载后，建议向下滚动一段，确保 "Posts" 区域可见。

### 4. 运行采集脚本

```bash
python main.py
```

脚本会自动滚动页面、提取帖子数据，并实时写入 `data.csv`。

---

## 中断后继续采集

采集过程中如果程序中断（网络波动、浏览器关闭等），按以下步骤恢复：

### 1. 查看最后采集日期

打开 `data.csv`，找到最后一条记录的 **发布时间** 列，记下日期。例如：

```
Tuesday, July 14, 2026 at 9:26 PM
```

### 2. 手动定位到该日期的帖子

在浏览器中回到目标主页，手动向下滚动，直到页面加载到**该日期附近或更早**的帖子。

### 3. 重新运行脚本

```bash
python main.py
```

脚本会从当前页面可见的帖子开始采集，已采集过的帖子会被 `aria-posinset` 索引自动跳过（**同一次运行期间不重复采集**）。

> **注意**：每次重新运行脚本，去重索引都会重置。因此需要你在上一步手动滚动到断点位置，避免大量重复。

---

## 去重机制

| 机制 | 说明 |
|------|------|
| **内存索引去重** | 使用帖子 DOM 元素的 `aria-posinset` 属性作为唯一标识，同一轮运行中不采集重复帖子 |
| **不持久化** | 每次启动脚本索引集为空，不读取历史 `data.csv` |

---

## 输出格式

每次运行实时追加写入 `data.csv`，列结构如下：

| 列名 | 说明 | 示例 |
|------|------|------|
| 发布者 | 发帖账号名称 | `Huawei` |
| 发布时间 | Facebook 显示的发布时间 | `Monday, July 27, 2026 at 2:54 PM` |
| 正文内容 | 帖子文字内容（含 `See less` 裁剪） | `The "OptVerse-CSU" team...` |
| 点赞数 | 点赞/心情总数 | `18` |
| 右边数据 | 评论/分享/观看等互动数据 | `3 comments 1 share` |
| 链接 | 帖子直达链接 | `https://www.facebook.com/...` |

---

## 配置说明

在 `main.py` 顶部可调整：

```python
tabPort = 2727          # 浏览器调试端口，与启动命令一致
CSV_PATH = r"...\data.csv"  # 输出文件路径
```

---

## 依赖安装

```bash
pip install DrissionPage
```

- **Python**: 3.8+
- **浏览器**: Chrome / Edge（需支持 `--remote-debugging-port`）

---

## 常见问题

### Q: 提示"未找到 Posts 相关的元素"

目标页面上 "Posts" 区域尚未加载。手动向下滚动页面，等待帖子列表出现。

### Q: 脚本运行很久没有新数据写入

可能已滚动到页面最早的内容。检查是否需要分页/换目标页。

### Q: 采集到的正文为空

该帖子可能为纯图片/视频内容，Facebook 未提供文字描述。

### Q: `aria-posinset` 获取不到

部分旧版帖子或特殊布局可能没有此属性，此时该帖子不会被去重保护，建议人工检查。

---

## 已知限制

### 中断恢复无法自动化

Facebook 的帖子日期筛选状态是纯前端内部状态，不持久化到浏览器存储（localStorage、IndexedDB 等均无相关数据），页面刷新即丢失。因此中断恢复仍需按照[中断后继续采集](#中断后继续采集)的步骤手动操作。
