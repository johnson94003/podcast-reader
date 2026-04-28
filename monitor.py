#!/usr/bin/env python3
"""
monitor.py — 掃描 YouTube 頻道，自動處理新影片

用法：
  python3 monitor.py            # 掃描並處理新影片
  python3 monitor.py --dry-run  # 只顯示新影片，不實際處理
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from builder import build_html, build_index_html
from downloader import download_srt, fetch_metadata, _find_yt_dlp
from segmenter import parse_srt
from translator import translate

# ── 設定 ──────────────────────────────────────────────────
CHANNELS = [
    "https://www.youtube.com/@FlorisGierman",
]
MAX_NEW_PER_RUN = 1        # 每次只處理最新一支，控制 API 費用
PLAYLIST_PEEK   = 10       # 每個頻道抓最新幾支來比對
PROCESSED_PATH  = Path(__file__).parent / "processed_videos.json"
OUTPUT_DIR      = Path(__file__).parent / "output"
CACHE_DIR       = Path(__file__).parent / "cache"
LAST_RUN_PATH   = CACHE_DIR / "last_run.json"


# ── 已處理清單 ────────────────────────────────────────────
def load_processed() -> set:
    if PROCESSED_PATH.exists():
        return set(json.loads(PROCESSED_PATH.read_text(encoding="utf-8")))
    return set()


def save_processed(processed: set):
    PROCESSED_PATH.write_text(
        json.dumps(sorted(processed), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── 取得頻道最新影片清單 ──────────────────────────────────
def get_channel_videos(channel_url: str) -> list[dict]:
    """
    用 yt-dlp 列出頻道最新影片
    回傳 [{"id": "xxx", "title": "...", "upload_date": "YYYYMMDD"}]
    """
    yt_dlp = _find_yt_dlp()
    result = subprocess.run(
        [
            yt_dlp,
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(upload_date>%Y%m%d,unknown)s",
            "--playlist-end", str(PLAYLIST_PEEK),
            f"{channel_url}/videos",
        ],
        capture_output=True, text=True,
    )

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        vid        = parts[0].strip()
        title      = parts[1].strip() if len(parts) > 1 else vid
        up_date    = parts[2].strip() if len(parts) > 2 else ""
        videos.append({
            "id":          vid,
            "title":       title,
            "upload_date": up_date,
            "url":         f"https://www.youtube.com/watch?v={vid}",
        })
    return videos


# ── 處理單支影片 ──────────────────────────────────────────
def process_video(video: dict) -> bool:
    """下載、翻譯、生成 HTML。成功回傳 True。"""
    url = video["url"]
    print(f"\n  🎬 {video['title']}")
    print(f"     {url}")

    try:
        video_id, srt_path = download_srt(url)
        meta  = fetch_metadata(url)
        cues  = parse_srt(srt_path)
        print(f"     共 {len(cues)} 條字幕")
        segs  = translate(cues, video_id)
        build_html(segs, video_id,
                   title=meta.get("title", ""),
                   channel=meta.get("channel", ""))
        print(f"     ✓ 完成：output/{video_id}.html")
        return True

    except Exception as e:
        print(f"     ✗ 失敗：{e}")
        return False


# ── 重建所有 HTML（cache 已存在的影片）────────────────────
def rebuild_all_html():
    """從 cache/ 重建所有影片的 HTML，確保部署的是最新版 template。"""
    rebuilt = 0
    for cache_file in sorted(CACHE_DIR.glob("*.json")):
        if cache_file.stem.endswith(".meta"):
            continue
        vid = cache_file.stem
        meta_file = CACHE_DIR / f"{vid}.meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        segs = json.loads(cache_file.read_text(encoding="utf-8"))
        build_html(segs, vid,
                   title=meta.get("title", ""),
                   channel=meta.get("channel", ""))
        rebuilt += 1
    if rebuilt:
        print(f"  已重建 {rebuilt} 支影片的 HTML")
    build_index_html()  # 同步更新首頁清單


# ── 主程式 ────────────────────────────────────────────────
def main():
    dry_run   = "--dry-run" in sys.argv
    processed = load_processed()

    print(f"\n🔍  掃描頻道...")
    print(f"   已處理過：{len(processed)} 支影片\n")

    new_videos: list[dict] = []

    for channel_url in CHANNELS:
        print(f"頻道：{channel_url}")
        videos = get_channel_videos(channel_url)

        for v in videos:
            if v["id"] in processed:
                print(f"  ✓  {v['title']}")
            else:
                print(f"  🆕 {v['title']}  ({v['upload_date']})")
                new_videos.append(v)

    if not new_videos:
        print("\n✅  沒有新影片，結束\n")
        _save_summary(status="no_new", new_videos=[], processed_videos=[])
        return

    print(f"\n共 {len(new_videos)} 支新影片")

    if dry_run:
        print("（dry-run 模式，不實際處理）\n")
        return

    # 每次最多處理 MAX_NEW_PER_RUN 支（新→舊順序）
    to_process = new_videos[:MAX_NEW_PER_RUN]
    remaining  = new_videos[MAX_NEW_PER_RUN:]
    if remaining:
        print(f"本次處理前 {MAX_NEW_PER_RUN} 支，其餘下次繼續\n")

    succeeded_videos = []
    failed_videos    = []
    for video in to_process:
        ok = process_video(video)
        if ok:
            processed.add(video["id"])
            succeeded_videos.append(video)
        else:
            failed_videos.append(video)

    save_processed(processed)
    print(f"\n📊  本次：{len(succeeded_videos)}/{len(to_process)} 支成功\n")
    _save_summary(
        status="processed" if succeeded_videos else "failed",
        new_videos=new_videos,
        processed_videos=succeeded_videos,
        failed_videos=failed_videos,
        remaining=remaining,
    )


def _save_summary(
    status: str,
    new_videos: list,
    processed_videos: list,
    failed_videos: list | None = None,
    remaining: list | None = None,
):
    """把本次執行結果寫成 JSON，供 GitHub Actions 寄信用。"""
    CACHE_DIR.mkdir(exist_ok=True)
    summary = {
        "date":        str(date.today()),
        "status":      status,          # "no_new" | "processed" | "failed"
        "new_found":   len(new_videos),
        "processed":   [{"id": v["id"], "title": v["title"], "url": v["url"]}
                        for v in processed_videos],
        "failed":      [{"id": v["id"], "title": v["title"], "url": v["url"]}
                        for v in (failed_videos or [])],
        "remaining":   len(remaining or []),
    }
    LAST_RUN_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✓ 執行摘要已儲存：{LAST_RUN_PATH}")


if __name__ == "__main__":
    main()
