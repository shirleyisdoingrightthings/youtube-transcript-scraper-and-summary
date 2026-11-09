# YouTube to Blog Workflow

End-to-end workflow that converts YouTube videos, podcasts, and technical talks into fact-checked Chinese deep-dive articles or dialogue transcripts, automatically synced to Notion.

## Workflow

```text
YouTube URL / Podcast Radar (radar.py)
  │
  ▼
1. Topic Assessment (Optional)
  └─ Skim transcript via free source (--prefer-free) & score across 4 editorial dimensions
  │
  ▼
2. Transcript Fetching (fetch_transcript.py)
  └─ Fetch timestamped transcript, verify >= 90% coverage, and save to transcript.json
  │
  ▼
3. Mode Routing & Drafting
  ├─ Mode A (Default): Illustrated Deep-Dive Article (skills/illustrated_deepdive.md)
  ├─ Mode B: Speaker-Attributed Dialogue / Talk Transcript (skills/dialogue_transcript.md)
  └─ Mode C: Multi-Source Industry Commentary (skills/observation_commentary.md)
  │
  ▼
4. Verification & Agent Council QA
  ├─ Fact-check numbers, proper nouns, and quotes against transcript.json & glossary.md
  └─ Run dual-reviewer (Progressive + Conservative) + Judge council to eliminate errors
  │
  ▼
5. Archive & Notion Sync (notion_upload.py)
  ├─ Save final Markdown and transcript.json under output/<Title>/
  └─ Idempotently publish to Notion & support collaborative revision via Notion comments
```

## Operation

1. **Run Podcast Radar (Optional)**: Run `python3 radar.py run --days 7` to scan 20 AI podcast channels for high-outperformance episodes.
2. **Convert a Video**: Send a YouTube URL and specify the desired output mode (Mode A deep-dive, Mode B transcript, or Mode C commentary).
3. **Revise & Ratchet**: Leave comments on the Notion page or in chat; the agent updates the draft and distills permanent rules into `glossary.md` and `skills/`.
