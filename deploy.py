#!/usr/bin/env python3
"""
deploy.py — 把 output/ 的 HTML 部署到 Netlify


用法：
  python3 deploy.py               # 部署所有 HTML
  python3 deploy.py VIDEO_ID      # 只確認某支影片存在後部署

需要在 .env 裡設定：
  NETLIFY_TOKEN=你的token
  NETLIFY_SITE_ID=（第一次跑完後自動寫入）
"""

import io
import json
import os
import sys
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

NETLIFY_TOKEN   = os.getenv("NETLIFY_TOKEN", "")
NETLIFY_SITE_ID = os.getenv("NETLIFY_SITE_ID", "")
OUTPUT_DIR      = Path(__file__).parent / "output"
ENV_PATH        = Path(__file__).parent / ".env"


def _headers():
    return {"Authorization": f"Bearer {NETLIFY_TOKEN}"}


def _build_zip() -> bytes:
    """把 output/ 所有 HTML 打包成 zip（in memory）"""
    buf = io.BytesIO()
    files = list(OUTPUT_DIR.glob("*.html"))
    if not files:
        raise FileNotFoundError("output/ 裡沒有 HTML 檔案")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
            print(f"  打包：{f.name}")
    buf.seek(0)
    return buf.read()


def _save_site_id(site_id: str):
    """把 NETLIFY_SITE_ID 寫回 .env，下次不用重建站台"""
    content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if "NETLIFY_SITE_ID" in content:
        lines = [
            f"NETLIFY_SITE_ID={site_id}" if l.startswith("NETLIFY_SITE_ID=") else l
            for l in content.splitlines()
        ]
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        with open(ENV_PATH, "a", encoding="utf-8") as f:
            f.write(f"\nNETLIFY_SITE_ID={site_id}\n")


def deploy():
    if not NETLIFY_TOKEN:
        print("❌  找不到 NETLIFY_TOKEN，請先在 .env 設定")
        sys.exit(1)

    print("\n📦  打包 output/ ...")
    zip_data = _build_zip()

    site_id = NETLIFY_SITE_ID

    # ── 第一次：建立新站台 ────────────────────────────────
    if not site_id:
        print("\n🌐  第一次部署，建立新站台...")
        r = requests.post(
            "https://api.netlify.com/api/v1/sites",
            headers=_headers(),
            json={"name": "podcast-reader"},
        )
        if r.status_code not in (200, 201):
            print(f"❌  建立站台失敗：{r.status_code} {r.text}")
            sys.exit(1)
        site_id = r.json()["id"]
        site_url = r.json()["ssl_url"] or r.json()["url"]
        _save_site_id(site_id)
        print(f"  ✓ 站台建立：{site_url}")

    # ── 部署 zip ──────────────────────────────────────────
    print(f"\n🚀  部署中...")
    r = requests.post(
        f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
        headers={**_headers(), "Content-Type": "application/zip"},
        data=zip_data,
    )
    if r.status_code not in (200, 201):
        print(f"❌  部署失敗：{r.status_code} {r.text[:300]}")
        sys.exit(1)

    data     = r.json()
    site_url = data.get("ssl_url") or data.get("url") or ""
    deploy_url = data.get("deploy_ssl_url") or data.get("deploy_url") or ""

    print(f"\n✅  部署完成！")
    print(f"   網站：{site_url}")
    print(f"   此次：{deploy_url}\n")

    # 印出所有影片的直接連結（含標題）
    html_files = sorted(OUTPUT_DIR.glob("*.html"))
    if html_files and site_url:
        print("📺  影片連結：")
        meta_dir = Path(__file__).parent / "cache"
        for f in html_files:
            vid = f.stem
            meta_path = meta_dir / f"{vid}.meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                label = f"{meta.get('title', vid)}  ／  {meta.get('channel', '')}"
            else:
                label = vid
            print(f"   {site_url}/{f.name}")
            print(f"   └─ {label}")
    print()


if __name__ == "__main__":
    deploy()
