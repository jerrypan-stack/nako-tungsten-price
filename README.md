# Nako 钨钢 ¥/克对照页

可分享的静态页：浏览器直接打开即可筛选、看排行、点「打开源站核对」。

## 公开地址

https://jerrypan-stack.github.io/nako-tungsten-price/

仓库：https://github.com/jerrypan-stack/nako-tungsten-price

## 本地打开

1. 进入本目录  
2. 双击 `index.html`，或用浏览器打开该文件  
3. （可选）若浏览器限制本地脚本，可在本目录执行：`python3 -m http.server 8765`，再访问 `http://localhost:8765/`

`index.html` 已内嵌全部数据，不依赖外网 API；`data.json` 为同源备份，部署时可不带。

## 重新部署

改完后在本目录 `git add` / `commit` / `push` 到 `main`，GitHub Pages 会自动更新。

## 口径摘要

- 汇率固定 **1 USD = ¥6.75**  
- 只统计 **有货** 且 **单粒约 ≤14g（含 1/2 oz ≈14.175g）**  
- 排行表「有货 / 没货」按品类对照范围标注，不编造缺货价  
- 比价单位：**¥/克**（不要只看包装价）  
- 数据日期见页面顶部 chip；链接曾做过 HTTP 抽检（见页内口径说明）
