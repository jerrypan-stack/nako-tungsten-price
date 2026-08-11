#!/usr/bin/env bash
# 本地一键更新价格/库存（同源抓取）→ 写 data.json 并同步进 index.html
set -euo pipefail
cd "$(dirname "$0")"
echo "▶ 开始抓取 + 多方法交叉验证（主解析 / 旁路端点 / 公式 / 同伴离群 / 有货）"
python3 scripts/refresh_prices.py
echo
echo "✓ 完成。检查 diff 后提交并推送 main，Pages 会自动更新："
echo "  git add data.json index.html && git commit -m 'chore: refresh tungsten prices' && git push"
