# Podcast Reader — 工作手冊

給 Claude 看的操作指南。每次收到新影片網址時，依照這份手冊執行。

## Claude 的自我更新規則

以下任一事件發生後，**立即**更新這份文件，不等對話結束：
- 修了 bug → 更新「常見問題」
- 加了功能 → 更新架構說明
- 改了設計決策 → 更新「不要動的部分」
- 踩到新坑 → 記錄原因與解法
- 新增 / 修改 secret、token、設定 → 更新對應章節

---

## 一、這個專案是什麼

輸入 YouTube 網址 → 輸出雙語閱讀 HTML，並部署到 GitHub Pages。
每個段落可以單獨播放，播完自動停住，支援連播（auto-advance）、繼續 / 重播，翻譯預設模糊、點擊顯示。
頂部顯示影片標題與頻道名稱。使用 Supabase 儲存閱讀進度（已讀段落、最後閱讀位置）。

---

## 二、檔案結構

```
podcast_reader/
├── main.py          # 入口，串接所有步驟
├── monitor.py       # GitHub Actions 用：掃描訂閱頻道，處理新影片
├── downloader.py    # yt-dlp 下載 SRT + 取得影片 metadata
├── segmenter.py     # 解析 SRT → Cue 物件列表
├── translator.py    # Claude API：語意分段 + 翻譯
├── builder.py       # 生成 HTML（含標題、頻道、播放器）+ build_index_html()
├── deploy.py        # 部署到 GitHub Pages（git push → gh-pages 分支）
├── run.command      # 雙擊執行（不需開終端機）
├── config.py        # API key、模型、批次大小
├── .env             # ANTHROPIC_API_KEY（本機用）
├── processed_videos.json  # 已處理影片清單（monitor.py 用）
├── subscriptions.json     # 訂閱頻道清單（monitor.py 用）
├── srt/             # 下載的 SRT 檔案（自動建立）
├── cache/           # 翻譯結果 JSON + metadata JSON（自動建立）
└── output/          # 輸出 HTML（自動建立）
```

---

## 三、環境需求

### Python 套件
```bash
pip install anthropic yt-dlp python-dotenv requests
```

### .env 設定（本機）
```
ANTHROPIC_API_KEY=sk-ant-你的金鑰
```

### GitHub Secrets（CI 用）
```
ANTHROPIC_API_KEY      # Claude API key
YOUTUBE_COOKIES        # yt-dlp cookie 字串（從 Chrome 匯出）
GMAIL_USER             # a0973271958@gmail.com（寄信用）
GMAIL_APP_PASSWORD     # Google App Password（16 碼，無空格）
```

### GitHub PAT（本機 push 用）
- 永不過期版本，儲存在 macOS 鑰匙圈（github.com / johnson94003）
- 權限：`repo` + `workflow`
- 若需重設：`security add-internet-password -U -s github.com -a johnson94003 -w <新token>`
- 同步更新 git remote：`git remote set-url origin "https://<新token>@github.com/johnson94003/podcast-reader.git"`

### 注意：yt-dlp 不在 PATH
安裝在 `~/Library/Python/3.9/bin/yt-dlp`，`downloader.py` 的 `_find_yt_dlp()` 會自動找到，不需手動設定。

### YouTube 字幕需要 Chrome cookie
部分影片需要驗證才能取得字幕，downloader 已設定 `--cookies-from-browser chrome`，確保 Chrome 有登入 YouTube。

### 本地伺服器（本地預覽用）
YouTube iframe 必須透過 http:// 載入，不能用 file://：
```bash
cd .../podcast_reader/output
python3 -m http.server 8765
```
啟動後用 `http://localhost:8765/{video_id}.html` 開啟。

---

## 四、執行方式

### 最簡單：雙擊 run.command
不需開終端機，輸入網址後自動翻譯 + 部署。

### 終端機執行
```bash
cd .../podcast_reader

# 一般執行（有 cache 就直接用）
python3 main.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 強制重新翻譯
python3 main.py "https://www.youtube.com/watch?v=VIDEO_ID" --retranslate

# 部署到 GitHub Pages
python3 deploy.py
```

### 只重新生成 HTML（不重新翻譯，調版面用）
```python
import json
from builder import build_html
from pathlib import Path

video_id = 'VIDEO_ID'
segs = json.loads(Path(f'cache/{video_id}.json').read_text())
meta = json.loads(Path(f'cache/{video_id}.meta.json').read_text())
build_html(segs, video_id, title=meta.get('title',''), channel=meta.get('channel',''))
```

---

## 五、完整流程說明

### Step 1｜下載 SRT + Metadata（downloader.py）

- `download_srt(url)`：優先下載手動字幕（en-orig / en），沒有才用自動生成
- `fetch_metadata(url)`：取得影片標題與頻道名稱，存成 `cache/{video_id}.meta.json`
- 已存在就跳過，不重複請求
- 輸出：`srt/{video_id}.en.srt` + `cache/{video_id}.meta.json`

meta.json 格式：
```json
{"video_id": "xxx", "title": "影片標題", "channel": "頻道名稱"}
```

### Step 2｜解析 SRT（segmenter.py）

- YouTube 自動生成 SRT 是「滾動字幕」格式，相鄰 cue 時間戳會重疊（這是正常的）
- 每個 Cue 物件帶有：index、start、end、text、start_sec、end_sec

### Step 3｜翻譯（translator.py）

**核心設計決策：Claude 只輸出 cue index，不輸出時間戳。**

原因：讓 Claude 輸出時間戳會猜錯，造成段落邊界重疊。

做法：
1. 每批 80 個 cue 送給 Claude（附帶前 5 個 cue 作為上下文）
2. Claude 回傳：哪些 cue index 屬於哪個段落 + 繁體中文翻譯 + 說話者
3. 程式從原始 Cue 物件取得精確時間戳

```json
// Claude 輸出格式
[{"cues": [0, 1, 2, 3], "zh": "翻譯", "speaker": "Guest"}]

// 程式轉換成
{"start": "00:00:00,160", "end": "00:00:08,559", "en": "...", "zh": "...", "speaker": "Guest"}
```

**JSON 解析：使用 `raw_decode` 而非 `rfind("]")`**

Claude 有時在 JSON 後面多輸出說明文字，`raw_decode` 從第一個 `[` 開始解析，遇到完整 JSON 就停止。

防護機制：
- 上下文 cue 的 index 不在 `valid_indices` 中，會被過濾掉
- 重複的 cue index 用 `covered` set 排除
- 遺漏的 cue 合併成 fallback 段落並警告
- 段落超過 30 秒會自動拆成兩段補譯
- 批次失敗時整批合併成單一段落，標記「（翻譯失敗）」，不中斷整體流程

cache 結構（`cache/{video_id}.json`）：
```json
[
  {
    "start": "HH:MM:SS,mmm",
    "end": "HH:MM:SS,mmm",
    "en": "英文原文",
    "zh": "繁體中文翻譯",
    "speaker": "Host | Guest | Narration"
  }
]
```

### Step 4｜生成 HTML（builder.py）

**build_html 簽名：**
```python
build_html(segments, video_id, title="", channel="", output_dir="output")
```

**build_index_html 簽名：**
```python
build_index_html(cache_dir="cache", output_dir="output")
```
掃描 cache/*.meta.json，生成影片清單首頁 output/index.html。

**標題顯示：** 頂部 player bar 顯示 `title`（粗體）與 `channel`（淡色小字）。

**關鍵：effective_end 計算**

YouTube SRT 的相鄰段落時間戳天然重疊，必須修正：
```python
def effective_end(i):
    raw_end = _time_to_seconds(segments[i]["end"])
    if i + 1 < len(segments):
        next_start = _time_to_seconds(segments[i + 1]["start"])
        return min(raw_end, next_start)   # ← 用下一段的開始時間截斷
    return raw_end
```

### Step 5｜部署（deploy.py）

- 在 `output/` 建立暫時 git repo，force push 到 `gh-pages` 分支
- 自動偵測 git remote URL，推算 `https://USER.github.io/REPO` 網址
- 部署完成後印出所有影片連結（含標題 + 頻道）

**GitHub Pages 網址：** https://johnson94003.github.io/podcast-reader

---

## 六、自動化（GitHub Actions）

### monitor.py
- 讀取 `subscriptions.json`，查詢各頻道最新影片
- 對照 `processed_videos.json`，找出未處理的新影片
- 每次只處理一支新影片（避免超時）
- 執行完後寫入 `cache/last_run.json`（供寄信用）
- `rebuild_all_html()`：從 cache 重建所有 HTML

### cache/last_run.json 格式
```json
{
  "date": "2026-04-28",
  "status": "no_new | processed | failed",
  "new_found": 0,
  "processed": [{"id": "...", "title": "...", "url": "..."}],
  "failed": [],
  "remaining": 0
}
```

### daily.yml（.github/workflows/）
- 每天 UTC 02:00（台灣 10:00）自動執行
- 步驟：checkout → install → write cookies → monitor.py → rebuild HTML → deploy gh-pages → commit cache 回 main → **寄信通知**
- 所有步驟加 `continue-on-error: true`，email 步驟加 `if: always()`
  → workflow 永遠以「成功」結束，GitHub 不會發原生失敗通知信
  → 出錯只由自訂 email 通報
- 寄信用 `dawidd6/action-send-mail@v3`，透過 Gmail SMTP
- 信件主旨範例：
  - 沒新影片：`Podcast Reader 2026-04-28 — 今天沒有新影片`
  - 有新影片：`Podcast Reader 2026-04-28 — 新增 1 支影片 ✅`
  - 失敗：`Podcast Reader 2026-04-28 — 處理失敗 ❌`
- commit cache 回 main 時先 `git pull --rebase` 避免 push 衝突

### rebuild_all_html() 注意事項
- `cache/*.json` 只處理有對應 `.meta.json` 的檔案
- `last_run.json` 等非影片 JSON 會被自動跳過（無 meta.json）
- 若新增其他非影片 JSON 到 cache，不需特別處理

### processed_videos.json 注意事項
- 本機處理的影片必須手動確認有加進去，否則 CI 每次都會重新嘗試處理
- 本機跑完 `main.py` 後，`processed_videos.json` 不會自動更新，需手動加入 video_id

### YouTube Cookie（CI 環境）
- CI 環境：讀取 `YOUTUBE_COOKIES` secret 寫成 `youtube_cookies.txt`
- `downloader.py` 偵測 `YOUTUBE_COOKIES_FILE` 環境變數，使用 `--cookies` + `--no-check-formats`
- `--no-check-formats` 是關鍵：繞過 n-challenge，避免 bot 偵測
- Cookie 有效期約數週，過期會出現 n-challenge 警告 → 需重新匯出並更新 `YOUTUBE_COOKIES` secret

---

## 七、HTML 播放器設計

### 功能特色
- 每段可單獨播放，播完自動停止
- 連播模式（▶▶ 連播）：播完自動進下一段
- 翻譯預設模糊，點擊顯示
- 已讀段落標記（配合 Supabase 同步）
- 支援手機版（640px 以下兩行式 player bar）

### 按鈕設計（每段兩顆）

| 按鈕 | class | 預設 | 說明 |
|------|-------|------|------|
| ▶ / ⏸ | `.seg-play-btn` | 永遠顯示 | 播放 / 繼續 / 暫停 |
| ↺ | `.seg-replay-btn` | 隱藏（`display:none`） | 從頭重播 |

**三種狀態：**
```
空白（未點擊）  → ▶ 只顯示播放鈕，↺ 隱藏
播放中          → ⏸（active 綠色）+ ↺ 同時顯示
暫停中          → ▶ + ↺ 同時顯示（↺ 不消失）
```

**播完自動停的行為：** 視為「結束」而非「暫停」，`activeIdx` 清空，按鈕回到空白（↺ 消失）。再按 ▶ 會從頭重播。

### 播放控制（JavaScript）

```javascript
togglePlay(idx, start, end)   // ▶/⏸ 按鈕觸發
  ├─ 播放中此段  → pauseVideo()（保留 activeSegEnd）
  ├─ 暫停中此段  → player.playVideo() 從目前位置繼續，恢復 segEnd
  └─ 其他        → _loadSeg()（從頭播放）

replaySeg(idx, start, end)    // ↺ 按鈕觸發 → 直接呼叫 _loadSeg()

_loadSeg(idx, start, end)     // 內部：載入新段落
  → 設定 activeIdx / activeSegEnd / segStart / segEnd
  → loading = true（防閃爍）
  → loadVideoById({startSeconds, endSeconds: end + 2})

playNext(fromIdx)             // 連播：自動播下一段
  → 由 RAF done + ENDED handler 呼叫（若 autoAdvance = true）
```

**關鍵變數：**
```javascript
activeIdx    // 目前選定的段落 index
activeSegEnd // 目前段落的結束點（暫停後仍保留，繼續播放時恢復用）
segStart     // RAF：不早於此時間停止（防 seek 後舊時間誤觸）
segEnd       // RAF：停止目標時間（暫停時清空，繼續時恢復）
loading      // loadVideoById 進行中旗標，忽略中間的 PAUSED 事件
autoAdvance  // 連播模式開關（預設 true）
```

### 精準停止（requestAnimationFrame）

```javascript
// 停止條件（三個 guard 同時成立）
t >= segStart              // 確認已進入新段落，防止 seek 後舊 t 誤觸
t <= segEnd + 2            // 防止過大的舊值誤觸（sanity check）
t >= segEnd - STOP_AHEAD   // 提前 150ms 停止，抵消 API 延遲

// 播完後清空所有狀態（視為結束，非暫停）
segStart = segEnd = activeSegEnd = null;
activeIdx = null;
setSegState(doneIdx, 'idle');
```

`loadVideoById` 的 `endSeconds: end + 2` 是備用保險，正常由 RAF 先到。

### 可調參數
```javascript
const STOP_AHEAD = 0.15;  // 停止提前量（秒）；偏早停 → 調小；偏晚停 → 調大
```

---

## 八、Supabase 閱讀進度

### 資料表（reading_progress）
```sql
CREATE TABLE reading_progress (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id),
  video_id text NOT NULL,
  read_segments integer[] DEFAULT '{}',
  last_segment integer,
  updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, video_id)  -- 每人每影片一筆
);
```

### 運作方式
- `loadProgress()`：讀取所有 row 並 merge（防止多 row 碎片化）
- `markRead(idx)`：debounced 1.5s，執行 delete + insert（確保只有一筆）
- 登入後自動同步，滾動到最後閱讀位置

---

## 九、說話者顏色對應

| 說話者 | 標籤顏色 |
|--------|----------|
| Host | 深綠 #2d6a4f |
| Guest | 深藍 #1d3557 |
| Narration | 棕色 #7b5e3a |

---

## 十、新影片操作 SOP

1. **執行主程式**
   ```bash
   cd .../podcast_reader
   python3 main.py "YouTube 網址"
   ```
   或雙擊 `run.command`

2. **等待完成**（每 80 cues ≈ 1 批次 ≈ 5-10 秒）

3. **本地預覽**（確認伺服器在跑）
   ```
   http://localhost:8765/{video_id}.html
   ```

4. **部署上線**
   ```bash
   python3 deploy.py
   ```

5. **驗證切點**，如有問題：
   - 系統性偏晚停 → 調大 `STOP_AHEAD`
   - 翻譯失敗段落 → 刪 cache，`--retranslate` 重跑

---

## 十一、常見問題

| 問題 | 原因 | 解法 |
|------|------|------|
| YouTube 播放器錯誤 153 | 用 file:// 開啟 | 改用本地伺服器（port 8765） |
| 找不到英文字幕 | 影片無字幕 或 需要 PO token | 確認 Chrome 有登入 YouTube |
| 翻譯段落對不上音檔 | 舊 cache 有問題 | 刪 cache，`--retranslate` 重跑 |
| 某幾批顯示「翻譯失敗」 | Claude 回傳格式錯誤 | 刪 cache 重跑，通常是偶發 |
| 按鈕閃爍 / 無法暫停 | loading flag 失效 | 確認 PAUSED handler 有 `if (loading) return` |
| 播完再按 ▶ 立刻又停 | activeIdx 未清空 | 確認 RAF 停止時有清空 activeIdx |
| 標題沒顯示 | meta.json 不存在或 title 是 video_id | 手動修正 meta.json 後 rebuild + deploy |
| GitHub Actions 無字幕 | n-challenge bot 偵測 | 確認 `--no-check-formats` 在 cookie 路徑 |
| CI push 被拒（diverged） | 本機有新 commit | `git pull --rebase origin main` 再 push |

---

## 十二、不要動的部分

- `translator.py`：Claude 只輸出 cue index，時間戳由程式取
- `translator.py`：`raw_decode` 解析 JSON，不用 `rfind("]")`
- `builder.py`：`effective_end()` 的 `min(raw_end, next_start)` 計算
- `builder.py`：RAF loop 的三重 guard 條件
- `builder.py`：RAF 停止後清空 `activeIdx`（視為結束非暫停）
- `builder.py`：`loading` flag 防止 PAUSED 事件閃爍
- `builder.py`：`activeSegEnd` 暫停時不清空，確保繼續播放功能正常
- `builder.py`：`togglePlay` 的三分支邏輯（播放中暫停 / 暫停繼續 / 從頭載入）
- `builder.py`：`setSegState(idx, state)` 統一管理三種按鈕狀態
- `downloader.py`：`--cookies-from-browser chrome`（移除會導致部分影片取不到字幕）
- `downloader.py`：`--no-check-formats`（CI cookie 路徑，移除會導致 n-challenge 失敗）
