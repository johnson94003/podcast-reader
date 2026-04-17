#!/usr/bin/env python3
"""
deploy.py — 把 output/ 的 HTML 部署到 GitHub Pages（gh-pages 分支）

用法：
  python3 deploy.py    # 部署所有 HTML
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
CACHE_DIR  = ROOT / "cache"


def get_remote_url() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=ROOT,
    )
    return result.stdout.strip()


def get_pages_url(remote_url: str) -> str:
    """https://github.com/USER/REPO.git  →  https://USER.github.io/REPO"""
    url = remote_url.rstrip("/").removesuffix(".git")
    if "github.com/" in url:
        slug = url.split("github.com/")[-1]
    elif "github.com:" in url:
        slug = url.split("github.com:")[-1]
    else:
        return ""
    parts = slug.split("/")
    if len(parts) == 2:
        return f"https://{parts[0]}.github.io/{parts[1]}"
    return ""


def deploy():
    html_files = list(OUTPUT_DIR.glob("*.html"))
    if not html_files:
        print("❌  output/ 裡沒有 HTML 檔案，請先執行 main.py 或 monitor.py")
        sys.exit(1)

    remote_url = get_remote_url()
    if not remote_url:
        print("❌  無法取得 git remote URL，請確認已設定 git remote origin")
        sys.exit(1)

    pages_url = get_pages_url(remote_url)

    print(f"\n📦  準備部署到 GitHub Pages（共 {len(html_files)} 個檔案）...")

    # 在 output/ 裡建立暫時的 git repo，force push 到 gh-pages 分支
    def run(cmd):
        subprocess.run(cmd, cwd=OUTPUT_DIR, check=True, capture_output=True)

    run(["git", "init"])
    run(["git", "config", "user.name", "deploy-script"])
    run(["git", "config", "user.email", "deploy@local"])
    run(["git", "add", "."])
    run(["git", "commit", "-m", "deploy [skip ci]"])

    print("🚀  推送到 gh-pages 分支...")
    result = subprocess.run(
        ["git", "push", "--force", remote_url, "HEAD:gh-pages"],
        cwd=OUTPUT_DIR, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"❌  Push 失敗：\n{result.stderr}")
        sys.exit(1)

    print(f"\n✅  部署完成！")
    if pages_url:
        print(f"   網站：{pages_url}")
        print(f"   （若首次啟用，請到 GitHub → Settings → Pages → 選 gh-pages 分支）\n")

    # 印出影片連結
    print("📺  影片連結：")
    for f in sorted(html_files):
        vid = f.stem
        if vid == "index":
            continue
        meta_path = CACHE_DIR / f"{vid}.meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            label = f"{meta.get('title', vid)}  ／  {meta.get('channel', '')}"
        else:
            label = vid
        if pages_url:
            print(f"   {pages_url}/{f.name}")
        print(f"   └─ {label}")
    print()


if __name__ == "__main__":
    deploy()
