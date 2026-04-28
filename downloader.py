import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _get_cookie_args() -> list:
    """
    CI 環境：若有 YOUTUBE_COOKIES_FILE 就用 --cookies；
             沒有 cookie 時改用 iOS client 繞過 bot 偵測。
    本機環境：使用 --cookies-from-browser chrome。
    """
    cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookies_file and Path(cookies_file).exists():
        # cookie 檔 + no-check-formats（跳過 n-challenge 格式驗證，字幕仍可正常下載）
        return [
            "--cookies", cookies_file,
            "--no-check-formats",
        ]
    if not os.getenv("CI"):  # GitHub Actions 自動設定 CI=true
        return ["--cookies-from-browser", "chrome"]
    # CI 無 cookie：用 iOS client，通常能繞過 bot 偵測
    return ["--extractor-args", "youtube:player_client=ios"]


def _find_yt_dlp() -> str:
    """找到 yt-dlp 的實際路徑（處理未加入 PATH 的情況）"""
    found = shutil.which("yt-dlp")
    if found:
        return found
    # pip install --user 會裝到 ~/Library/Python/X.Y/bin/
    home = Path.home()
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        home / f"Library/Python/{ver}/bin/yt-dlp",
        home / ".local/bin/yt-dlp",
        Path(sys.executable).parent / "yt-dlp",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "yt-dlp"  # 最後嘗試，讓系統報錯


def extract_video_id(url: str) -> str:
    patterns = [
        r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"無法從網址擷取 video ID：{url}")


def download_srt(url: str, srt_dir: str = "srt") -> tuple[str, str]:
    """
    下載 YouTube 英文字幕。
    優先順序：en-orig（原始上傳）→ en（手動）→ en（自動生成）
    回傳 (video_id, srt_path)。
    """
    Path(srt_dir).mkdir(exist_ok=True)
    video_id = extract_video_id(url)

    # yt-dlp 可能輸出 .en-orig.srt 或 .en.srt，都接受
    candidates = [
        f"{srt_dir}/{video_id}.en-orig.srt",
        f"{srt_dir}/{video_id}.en.srt",
    ]

    # 已存在就直接回傳
    for path in candidates:
        if Path(path).exists():
            print(f"  字幕已存在：{path}")
            return video_id, path

    yt_dlp = _find_yt_dlp()
    base_cmd = [
        yt_dlp,
        *_get_cookie_args(),
        "--skip-download",
        "--sub-format", "srt",
        "--output", f"{srt_dir}/%(id)s.%(ext)s",
        url,
    ]

    # 1. 先試原始字幕（en-orig）和手動字幕（en）
    print("  嘗試下載手動字幕（en-orig / en）...")
    result = subprocess.run(
        base_cmd + ["--write-subs", "--sub-lang", "en-orig,en"],
        capture_output=True, text=True,
    )
    for path in candidates:
        if Path(path).exists():
            print(f"  ✓ 手動字幕：{path}")
            return video_id, path

    # 2. Fallback：自動生成字幕
    print("  無手動字幕，改用自動生成字幕...")
    result = subprocess.run(
        base_cmd + ["--write-auto-subs", "--sub-lang", "en"],
        capture_output=True, text=True,
    )
    for path in candidates:
        if Path(path).exists():
            print(f"  ✓ 自動字幕：{path}")
            return video_id, path

    raise FileNotFoundError(
        f"找不到英文字幕。yt-dlp 輸出：\n{result.stdout}\n{result.stderr}"
    )


def fetch_metadata(url: str, meta_dir: str = "cache") -> dict:
    """
    取得影片標題與頻道名稱，存成 cache/{video_id}.meta.json。
    若已存在則直接讀取，不重複請求。
    """
    video_id = extract_video_id(url)
    meta_path = Path(meta_dir) / f"{video_id}.meta.json"

    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))

    yt_dlp = _find_yt_dlp()
    result = subprocess.run(
        [yt_dlp, *_get_cookie_args(),
         "--skip-download", "--print", "%(title)s\n%(channel)s", url],
        capture_output=True, text=True,
    )
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    meta = {
        "video_id": video_id,
        "title":   lines[0] if len(lines) > 0 else video_id,
        "channel": lines[1] if len(lines) > 1 else "",
    }
    Path(meta_dir).mkdir(exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
