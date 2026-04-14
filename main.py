#!/usr/bin/env python3
"""
podcast_reader — YouTube Podcast 雙語閱讀器

用法：
  python main.py <youtube_url>

  # 強制重新翻譯（忽略 cache）
  python main.py <youtube_url> --retranslate
"""

import sys
from pathlib import Path

from builder import build_html
from downloader import download_srt, fetch_metadata
from segmenter import parse_srt
from translator import translate


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    url = args[0]
    retranslate = "--retranslate" in args

    print(f"\n🎙  Podcast Reader")
    print(f"   URL: {url}\n")

    # ── 1. 下載字幕 + 取得標題 ──────────────────────────────
    print("[1/4] 下載字幕...")
    video_id, srt_path = download_srt(url)
    meta = fetch_metadata(url)
    print(f"  📺 {meta['title']}  ／  {meta['channel']}")

    # ── 2. 解析 SRT ──────────────────────────────────────────
    print("[2/4] 解析 SRT...")
    cues = parse_srt(srt_path)
    print(f"  共 {len(cues)} 條字幕")

    # ── 3. 翻譯 ─────────────────────────────────────────────
    print("[3/4] 翻譯...")
    if retranslate:
        cache_path = Path("cache") / f"{video_id}.json"
        if cache_path.exists():
            cache_path.unlink()
            print("  已清除 cache，重新翻譯")
    segments = translate(cues, video_id)

    # ── 4. 生成 HTML ─────────────────────────────────────────
    print("[4/4] 生成 HTML...")
    output_path = build_html(segments, video_id, title=meta["title"], channel=meta["channel"])

    print(f"\n✅  完成！請用瀏覽器開啟：")
    print(f"   {output_path}\n")


if __name__ == "__main__":
    main()
