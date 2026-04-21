# Examples

几个常用场景的端到端脚本。跑之前先 `goofish auth login <cookies.json>`。

| 文件 | 场景 |
|---|---|
| `watch_to_autoreply.sh` | 把 `message watch` 的 JSONL 流接到自定义回复逻辑 |
| `publish_from_folder.py` | 按文件夹批量发布商品（自带 1 写/分钟节流） |
