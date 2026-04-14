# Podcast Reader — 工作手冊

給 Claude 看的操作指南。每次收到新影片網址時，依照這份手冊執行。

---

## 一、這個專案是什麼

輸入 YouTube 網址 → 輸出雙語閱讀 HTML，並部署到 Netlify。
每個段落可以單獨播放，播完自動停住，支援繼續 / 重播，翻譯預設模糊、點擊顯示。
頂部顯示影片標題與頻道名稱。

---

## 二、檔案結構

```
podcast_reader/
├── main.py          # 入口，串接所有步驟
├── downloader.py    # yt-dlp 下載 SRT + 取得影片 metadata
├── segmenter.py     # 解析 SRT → Cue 物件列表
├── translator.py    # Claude API：語意分段 + 翻譯
├── builder.py       # 生成 HTML（含標題、頻道、播放器）
├── deploy.py        # 部署到 Netlify
├── run.command      # 雙擊執行（不需開終端機）
├── config.py        # API key、模型、批次大小
├── .env             # ANTHROPIC_API_KEY + NETLIFY_TOKEN + NETLIFY_SITE_ID
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

### .env 設定
```
ANTHROPIC_API_KEY=sk-ant-你的金鑰
NETLIFY_TOKEN=nfp_你的token
NETLIFY_SITE_ID=（第一次部署後自動寫入）
```

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

# 部署到 Netlify
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

- 把 `output/` 所有 HTML 打包成 zip 上傳到 Netlify
- 第一次會建立新站台並把 `NETLIFY_SITE_ID` 寫回 `.env`
- 部署完成後印出所有影片連結（含標題 + 頻道）

---

## 六、HTML 播放器設計

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
```

**關鍵變數：**
```javascript
activeIdx    // 目前選定的段落 index
activeSegEnd // 目前段落的結束點（暫停後仍保留，繼續播放時恢復用）
segStart     // RAF：不早於此時間停止（防 seek 後舊時間誤觸）
segEnd       // RAF：停止目標時間（暫停時清空，繼續時恢復）
loading      // loadVideoById 進行中旗標，忽略中間的 PAUSED 事件
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

## 七、說話者顏色對應

| 說話者 | 標籤顏色 |
|--------|----------|
| Host | 深綠 #2d6a4f |
| Guest | 深藍 #1d3557 |
| Narration | 棕色 #7b5e3a |

---

## 八、新影片操作 SOP

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

## 九、常見問題

| 問題 | 原因 | 解法 |
|------|------|------|
| YouTube 播放器錯誤 153 | 用 file:// 開啟 | 改用本地伺服器（port 8765） |
| 找不到英文字幕 | 影片無字幕 或 需要 PO token | 確認 Chrome 有登入 YouTube |
| 翻譯段落對不上音檔 | 舊 cache 有問題 | 刪 cache，`--retranslate` 重跑 |
| 某幾批顯示「翻譯失敗」 | Claude 回傳格式錯誤 | 刪 cache 重跑，通常是偶發 |
| 按鈕閃爍 / 無法暫停 | loading flag 失效 | 確認 PAUSED handler 有 `if (loading) return` |
| 播完再按 ▶ 立刻又停 | activeIdx 未清空 | 確認 RAF 停止時有清空 activeIdx |
| 標題沒顯示 | meta.json 不存在 | 執行 `fetch_metadata(url)` 補建 |
| Netlify 401 Access Denied | Token 過期 | 重新產生 token 更新 .env |

---

## 十、不要動的部分

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
