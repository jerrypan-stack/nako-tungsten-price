# Nako 钨钢 ¥/克对照页

可分享的静态页：浏览器直接打开即可筛选、看排行、点「打开源站核对」。

## 公开地址

https://jerrypan-stack.github.io/nako-tungsten-price/

仓库：https://github.com/jerrypan-stack/nako-tungsten-price

## 一键更新价格/库存

页面顶部按钮会打开 GitHub Actions 工作流页：点 **Run workflow**，约 8–15 分钟后刷新本页。

- Actions：https://github.com/jerrypan-stack/nako-tungsten-price/actions/workflows/update-prices.yml  
- 本地：`./update.sh`（同源抓取 → 写 `data.json` → 同步进 `index.html`）  
- 定时：每天 09:00（中国时间）自动跑一次 cron  

### 交叉验证（≥3 种不同方法，不是同脚本连跑 3 次）

1. **主解析**：现有产品页 / Shopify `.json` / TW 行解析  
2. **旁路端点**：Shopify `.js` 或 TW 次级选择器（完整抓取时）  
3. **公式闭合**：`pack USD × 6.75 / (qty × oz × 28.3495)`，以及 oz↔g  
4. **同伴离群**：同品类同克重 `$/g` 相对中位数异常则剔除/待审  
5. **有货一致性**：有货标记与可发布标价一致  

发布规则：至少 **2** 种方法在价格/库存/粒数上一致才写入公开数据；否则重试后排除并记入 `needs_review`。

## 本地打开

1. 进入本目录  
2. 双击 `index.html`，或用浏览器打开该文件  
3. （可选）`python3 -m http.server 8765` → `http://localhost:8765/`

`index.html` 已内嵌全部数据；`data.json` 为同源备份。

## 口径摘要

- 汇率固定 **1 USD = ¥6.75**  
- 只统计 **有货** 且 **单粒约 ≤14g（含 1/2 oz）**  
- 支持人民币 / 美元视角与 Nail 等品类  
- 比价单位：**¥/克** 或 **$/g**（不要只看包装价）  
- 上次更新与「已用 N 种方法交叉验证」见页顶刷新条
