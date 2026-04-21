#!/usr/bin/env bash
# 把 `goofish message watch` 的 JSONL 流接到一个自定义回复脚本。
# 只处理 event=message，其余（read / new_msg）忽略。
#
# 用法：./watch_to_autoreply.sh
# 依赖：jq

set -euo pipefail

goofish message watch | while IFS= read -r line; do
  event=$(echo "$line" | jq -r '.event // empty')
  [[ "$event" != "message" ]] && continue

  cid=$(echo "$line"        | jq -r '.cid')
  toid=$(echo "$line"       | jq -r '.send_user_id')
  text=$(echo "$line"       | jq -r '.send_message')
  sender=$(echo "$line"     | jq -r '.send_user_name')

  echo "[recv] cid=$cid from=$sender($toid): $text" >&2

  # === 你的回复逻辑在这里 ===
  reply="你好 $sender，我稍后回复你。"

  goofish message send "$cid" "$toid" --text "$reply" >/dev/null
  echo "[reply] → $reply" >&2
done
