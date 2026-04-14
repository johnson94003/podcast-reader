#!/bin/bash
# 雙擊這個檔案就能跑，不需要開終端機

cd "$(dirname "$0")"

echo "=============================="
echo "  Podcast Reader"
echo "=============================="
echo ""
echo "請貼上 YouTube 網址："
read -r URL

if [ -z "$URL" ]; then
  echo "❌ 沒有輸入網址"
  read -p "按 Enter 關閉..."
  exit 1
fi

echo ""
python3 main.py "$URL"

echo ""
echo "正在部署到 Netlify..."
python3 deploy.py

echo ""
read -p "按 Enter 關閉視窗..."
