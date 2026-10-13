# 字幕抓取异常记录

- **2026-10-13（二）· Josh Woodward × Lenny's Podcast（https://youtu.be/3I6QYkccd3o ）**：阶段 -1 按规范跑 `fetch_transcript.py --prefer-free`，exit 1，三层全挂：① `www.youtube.com:443` 被云端会话出站代理拒绝（CONNECT 403，环境网络策略），oEmbed 拿不到标题、时长无从校验；② 免费源缺依赖 `youtube_transcript_api`（容器未装 requirements）；③ 付费源 `YOUTUBE_TRANSCRIPT_API_KEY` 未配置（无 `.env`），且 `api.youtube-transcript.io` 同样被代理拒绝。**处理**：未降级、未重试，按 Step 5 向用户汇报；本次选题预判改用用户上传的 Lenny's 官方 txt 逐字稿，与 API 字幕的比对待网络放行后补做。**解决方案**：在云端环境设置的 Network access 里放行 `www.youtube.com`、`api.youtube-transcript.io`（或改用本地会话），并配好 `.env`、`pip install -r requirements.txt`。
