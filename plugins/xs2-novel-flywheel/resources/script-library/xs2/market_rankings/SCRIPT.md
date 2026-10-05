# XS2 Market Rankings

从知乎盐选公开榜单接口抓取榜单快照，保存到当前 Workflow Workspace 的 `market/zhihu-ranking.json`。脚本只做抓取、结构化和落盘，不调用模型，也不会保存账号、Cookie 或会员正文。

命令：

- `refresh --top-n 100`：抓取并保存最新榜单快照。
