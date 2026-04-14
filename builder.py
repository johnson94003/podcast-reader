import json
from pathlib import Path

SPEAKER_STYLE = {
    "Host":      {"bg": "#2d6a4f", "label": "Host"},
    "Guest":     {"bg": "#1d3557", "label": "Guest"},
    "Narration": {"bg": "#7b5e3a", "label": "Narration"},
}


def _time_to_seconds(t: str) -> float:
    t = t.strip()
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _format_time(sec: float) -> str:
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _segment_html(seg: dict, idx: int, play_end_sec: float) -> str:
    """
    play_end_sec：實際播放結束點，用 min(raw_end, next_start) 計算，
    避免相鄰段落時間戳重疊造成的音檔錯位。
    """
    start_sec = _time_to_seconds(seg["start"])
    speaker   = seg.get("speaker", "Host")
    style     = SPEAKER_STYLE.get(speaker, SPEAKER_STYLE["Host"])
    time_disp = _format_time(start_sec)

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    return f"""  <div class="segment" data-start="{start_sec:.3f}" data-end="{play_end_sec:.3f}" id="seg-{idx}">
    <div class="seg-header">
      <span class="speaker-tag" style="background:{style['bg']}">{style['label']}</span>
      <span class="ts">{time_disp}</span>
      <div class="seg-controls">
        <button class="seg-replay-btn" id="seg-{idx}-replay"
                onclick="replaySeg({idx},{start_sec:.3f},{play_end_sec:.3f})"
                title="從頭重播此段" style="display:none">↺</button>
        <button class="seg-play-btn" id="seg-{idx}-play"
                onclick="togglePlay({idx},{start_sec:.3f},{play_end_sec:.3f})"
                title="播放 / 繼續 / 暫停">▶</button>
      </div>
    </div>
    <div class="seg-body">
      <p class="en">{esc(seg.get('en', ''))}</p>
      <p class="zh" onclick="this.classList.toggle('zh-visible')">{esc(seg.get('zh', ''))}</p>
    </div>
  </div>"""


def build_html(
    segments: list[dict],
    video_id: str,
    title: str = "",
    channel: str = "",
    output_dir: str = "output",
) -> str:
    Path(output_dir).mkdir(exist_ok=True)
    output_path = Path(output_dir) / f"{video_id}.html"

    # 計算每段的實際播放結束點：min(自身 end, 下一段 start)
    # 這樣可以修正 Claude 分段時造成的時間戳重疊問題
    def effective_end(i: int) -> float:
        raw_end = _time_to_seconds(segments[i]["end"])
        if i + 1 < len(segments):
            next_start = _time_to_seconds(segments[i + 1]["start"])
            return min(raw_end, next_start)
        return raw_end

    segments_html = "\n".join(
        _segment_html(s, i, effective_end(i))
        for i, s in enumerate(segments)
    )
    page_title   = title or f"Podcast — {video_id}"
    channel_disp = channel or ""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f5f0e8;
      color: #2c2c2c;
      min-height: 100vh;
    }}

    /* ── Sticky player bar ── */
    #player-bar {{
      position: sticky;
      top: 0;
      z-index: 200;
      background: #fffdf8;
      border-bottom: 1px solid #ddd5c4;
      padding: 10px 20px;
      display: flex;
      align-items: center;
      gap: 14px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    }}
    #yt-wrap {{
      flex-shrink: 0;
      width: 140px; height: 79px;
      border-radius: 8px;
      overflow: hidden;
      background: #000;
    }}
    #yt-wrap iframe {{ display: block; }}

    #now-playing {{
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    #video-meta {{
      display: flex;
      flex-direction: column;
      gap: 1px;
      margin-bottom: 2px;
    }}
    #video-title {{
      font-size: 13px;
      font-weight: 600;
      color: #2c2c2c;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    #video-channel {{
      font-size: 11px;
      color: #aaa;
    }}
    #now-time {{
      font-size: 12px;
      color: #999;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.3px;
    }}
    #now-text {{
      font-size: 13px;
      line-height: 1.5;
      color: #555;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    /* ── Language toggle ── */
    #lang-toggle {{
      display: flex;
      gap: 4px;
      flex-shrink: 0;
    }}
    .lang-btn {{
      padding: 5px 10px;
      border: 1px solid #ccc;
      border-radius: 14px;
      background: white;
      font-size: 12px;
      cursor: pointer;
      color: #555;
      transition: all 0.15s;
    }}
    .lang-btn.active {{
      background: #2d6a4f;
      border-color: #2d6a4f;
      color: white;
    }}

    /* ── Transcript ── */
    #transcript {{
      max-width: 820px;
      margin: 0 auto;
      padding: 28px 16px 80px;
    }}

    .segment {{
      background: white;
      border-radius: 12px;
      border: 2px solid transparent;
      margin-bottom: 10px;
      padding: 14px 16px;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .segment.playing {{
      border-color: #2d6a4f;
      box-shadow: 0 0 0 3px rgba(45,106,79,0.12);
    }}

    .seg-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .speaker-tag {{
      color: white;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      padding: 3px 9px;
      border-radius: 10px;
    }}
    .ts {{
      font-size: 12px;
      color: #aaa;
      font-variant-numeric: tabular-nums;
    }}

    /* ── Per-segment controls（播放 + 重播）── */
    .seg-controls {{
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }}
    .seg-play-btn {{
      width: 32px; height: 32px;
      border-radius: 50%;
      border: none;
      background: #eae5dc;
      color: #555;
      font-size: 12px;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.15s, color 0.15s;
    }}
    .seg-play-btn:hover  {{ background: #2d6a4f; color: white; }}
    .seg-play-btn.active {{ background: #2d6a4f; color: white; }}

    .seg-replay-btn {{
      width: 28px; height: 28px;
      border-radius: 50%;
      border: 1px solid #d0c9be;
      background: none;
      color: #aaa;
      font-size: 12px;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: all 0.15s;
    }}
    .seg-replay-btn:hover {{ background: #f0ede6; color: #555; border-color: #bbb; }}

    /* ── Bilingual text ── */
    .seg-body {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    .en {{
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 15px;
      line-height: 1.75;
      color: #2c2c2c;
    }}
    .zh {{
      font-size: 14px;
      line-height: 1.75;
      color: #888;
      cursor: pointer;
      position: relative;
      filter: blur(3px);
      transition: filter 0.25s, color 0.25s;
      user-select: none;
    }}
    .zh::after {{
      content: "點擊顯示";
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: #aaa;
      pointer-events: none;
    }}
    .zh.zh-visible {{
      filter: none;
      color: #444;
      cursor: default;
    }}
    .zh.zh-visible::after {{ display: none; }}

    /* ── Language mode overrides ── */
    body.mode-en .seg-body  {{ grid-template-columns: 1fr; }}
    body.mode-en .zh        {{ display: none; }}
    body.mode-zh .seg-body  {{ grid-template-columns: 1fr; }}
    body.mode-zh .en        {{ display: none; }}
    body.mode-zh .zh        {{ filter: none; color: #2c2c2c; cursor: default; }}
    body.mode-zh .zh::after {{ display: none; }}

    /* ── Mobile ── */
    @media (max-width: 640px) {{
      #yt-wrap {{ width: 100px; height: 56px; }}
      .seg-body {{ grid-template-columns: 1fr; }}
      body.mode-both .zh {{ filter: blur(3px); }}
      body.mode-both .zh.zh-visible {{ filter: none; }}
    }}
  </style>
</head>
<body class="mode-both">

  <!-- ── Player bar (no global play/pause button) ── -->
  <div id="player-bar">
    <div id="yt-wrap">
      <div id="yt-player"></div>
    </div>
    <div id="now-playing">
      <div id="video-meta">
        <span id="video-title">{page_title}</span>
        {'<span id="video-channel">' + channel_disp + '</span>' if channel_disp else ''}
      </div>
      <div id="now-time">0:00</div>
      <div id="now-text">點擊段落的 ▶ 開始播放</div>
    </div>
    <div id="lang-toggle">
      <button class="lang-btn"        onclick="setMode('en')"   title="只顯示英文">EN</button>
      <button class="lang-btn active" onclick="setMode('both')" title="雙語">EN+中</button>
      <button class="lang-btn"        onclick="setMode('zh')"   title="只顯示中文">中</button>
    </div>
  </div>

  <!-- ── Transcript ── -->
  <div id="transcript">
{segments_html}
  </div>

  <!-- ── YouTube IFrame API ── -->
  <script>
    const VIDEO_ID   = "{video_id}";
    const STOP_AHEAD = 0.15;   // 提前 150ms 停止，抵消 YouTube API 延遲

    let player;
    let activeIdx    = null;   // 目前選定的段落 index
    let activeSegEnd = null;   // 目前段落的結束點（暫停後仍保留，用於繼續播放）
    let segStart     = null;   // RAF：不早於此時間停止
    let segEnd       = null;   // RAF：停止目標時間
    let loading      = false;  // loadVideoById 進行中，忽略中間的 PAUSED 事件
    let rafRunning   = false;  // requestAnimationFrame loop 是否在跑
    let lastUITime   = 0;      // 上次 UI 更新時間（ms）

    const segs = Array.from(document.querySelectorAll('.segment'));

    // ── YouTube API ───────────────────────────────────────
    (function() {{
      const s = document.createElement('script');
      s.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(s);
    }})();

    window.onYouTubeIframeAPIReady = function() {{
      player = new YT.Player('yt-player', {{
        width: '140', height: '79',
        videoId: VIDEO_ID,
        playerVars: {{ controls: 0, modestbranding: 1, rel: 0 }},
        events: {{ onStateChange: onStateChange }}
      }});
    }};

    function onStateChange(e) {{
      if (e.data === YT.PlayerState.PLAYING) {{
        loading = false;
        startTicker();
        if (activeIdx !== null) setSegState(activeIdx, 'playing');

      }} else if (e.data === YT.PlayerState.ENDED) {{
        // YouTube endSeconds 備用停止（RAF 通常先到）
        loading      = false;
        segStart     = null;
        segEnd       = null;
        activeSegEnd = null;
        stopTicker();
        segs.forEach(s => s.classList.remove('playing'));
        resetAllSegs();
        activeIdx = null;

      }} else if (e.data === YT.PlayerState.PAUSED) {{
        if (loading) return;   // loadVideoById 中間的假 PAUSED，忽略
        stopTicker();
        segStart = null;
        segEnd   = null;
        if (activeIdx !== null) setSegState(activeIdx, 'paused');
        // 保留 highlight，讓使用者知道停在哪段
      }}
      // BUFFERING(3) / UNSTARTED(-1)：不動 UI
    }}

    // ── 播放 / 繼續 / 暫停（三合一）────────────────────
    function togglePlay(idx, start, end) {{
      if (!player) return;
      const state = player.getPlayerState();
      const isPlaying = activeIdx === idx &&
                        (state === YT.PlayerState.PLAYING ||
                         state === YT.PlayerState.BUFFERING);
      const isPaused  = activeIdx === idx &&
                        state === YT.PlayerState.PAUSED;

      if (isPlaying) {{
        // 正在播 → 暫停（保留 activeSegEnd 供繼續用）
        player.pauseVideo();

      }} else if (isPaused) {{
        // 暫停中 → 從目前位置繼續，恢復 RAF 目標
        const t = player.getCurrentTime();
        segStart = t;
        segEnd   = activeSegEnd;   // 用保留的結束點
        player.playVideo();

      }} else {{
        // 其他段落或未開始 → 從頭播放此段
        _loadSeg(idx, start, end);
      }}
    }}

    // ── 重播（永遠從頭開始）──────────────────────────────
    function replaySeg(idx, start, end) {{
      _loadSeg(idx, start, end);
    }}

    // ── 內部：載入並播放新段落 ───────────────────────────
    function _loadSeg(idx, start, end) {{
      activeIdx    = idx;
      activeSegEnd = end;   // 暫停後繼續用的結束點
      segStart     = start;
      segEnd       = end;
      loading      = true;
      resetAllSegs();
      setSegState(idx, 'playing');
      highlightSeg(idx);
      player.loadVideoById({{
        videoId: VIDEO_ID,
        startSeconds: start,
        endSeconds: end + 2   // YouTube 備用停止點
      }});
    }}

    // ── 立刻高亮指定段落 ──────────────────────────────────
    function highlightSeg(idx) {{
      segs.forEach(s => s.classList.remove('playing'));
      const segEl = document.getElementById('seg-' + idx);
      if (!segEl) return;
      segEl.classList.add('playing');
      const enEl = segEl.querySelector('.en');
      if (enEl) document.getElementById('now-text').textContent = enEl.textContent;
    }}

    // ── 設定單段的按鈕狀態 ───────────────────────────────
    // state: 'idle' | 'playing' | 'paused'
    function setSegState(idx, state) {{
      const playBtn   = document.getElementById('seg-' + idx + '-play');
      const replayBtn = document.getElementById('seg-' + idx + '-replay');
      if (!playBtn || !replayBtn) return;

      if (state === 'playing') {{
        playBtn.textContent = '⏸';
        playBtn.classList.add('active');
        replayBtn.style.display = '';       // 顯示重播按鈕
      }} else if (state === 'paused') {{
        playBtn.textContent = '▶';
        playBtn.classList.remove('active');
        replayBtn.style.display = '';       // 暫停時也顯示重播
      }} else {{                             // idle
        playBtn.textContent = '▶';
        playBtn.classList.remove('active');
        replayBtn.style.display = 'none';   // 閒置時隱藏重播
      }}
    }}

    function resetAllSegs() {{
      segs.forEach(seg => {{
        const i = parseInt(seg.id.replace('seg-', ''));
        setSegState(i, 'idle');
      }});
    }}

    // ── RAF loop（~16ms，遠比 setInterval 精準）─────────
    function startTicker() {{
      if (rafRunning) return;
      rafRunning = true;
      requestAnimationFrame(rafLoop);
    }}

    function stopTicker() {{
      rafRunning = false;
    }}

    function rafLoop() {{
      if (!rafRunning) return;
      requestAnimationFrame(rafLoop);   // 先掛下一幀，確保 loop 不中斷

      if (!player || !player.getCurrentTime) return;
      const t = player.getCurrentTime();

      // ── 精準停止 ──────────────────────────────────────
      // 條件：segEnd 已設定 AND 時間在合理範圍內（防止 seek 後舊 t 誤觸）
      // t <= segEnd + 2：如果 t 已遠超 segEnd，很可能是 getCurrentTime 回傳了舊值
      if (segEnd !== null && segStart !== null &&
          t >= segStart &&              // 確認已進入這個段落的時間範圍
          t <= segEnd + 2 &&            // 防止 seek 後舊時間誤觸
          t >= segEnd - STOP_AHEAD) {{  // 提前 STOP_AHEAD 秒停止
        // 播完：視為「結束」而非「暫停」，清空所有狀態
        segStart     = null;
        segEnd       = null;
        activeSegEnd = null;
        const doneIdx = activeIdx;
        activeIdx    = null;          // 清空後 PAUSED 事件不會誤判為繼續
        if (doneIdx !== null) setSegState(doneIdx, 'idle');
        segs.forEach(s => s.classList.remove('playing'));
        player.pauseVideo();
        return;
      }}

      // ── UI 更新限速（每 250ms 更新一次，避免 layout thrashing）──
      const now = performance.now();
      if (now - lastUITime < 250) return;
      lastUITime = now;

      document.getElementById('now-time').textContent = fmt(t);

      // 找到當前時間對應的段落（highlight + 捲動）
      let active = null;
      for (const seg of segs) {{
        const s = parseFloat(seg.dataset.start);
        const e = parseFloat(seg.dataset.end);
        if (t >= s && t < e) {{ active = seg; break; }}
        if (s > t + 1) break;
      }}

      segs.forEach(s => s.classList.remove('playing'));
      if (active) {{
        active.classList.add('playing');
        const enEl = active.querySelector('.en');
        if (enEl) document.getElementById('now-text').textContent = enEl.textContent;

        const rect = active.getBoundingClientRect();
        if (rect.top < 110 || rect.bottom > window.innerHeight - 20) {{
          active.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        }}
      }}
    }}

    // ── 時間格式化 ────────────────────────────────────────
    function fmt(sec) {{
      sec = Math.floor(sec);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      return h
        ? h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0')
        : m + ':' + String(s).padStart(2,'0');
    }}

    // ── 語言模式 ──────────────────────────────────────────
    function setMode(mode) {{
      document.body.className = 'mode-' + mode;
      document.querySelectorAll('.lang-btn').forEach((btn, i) => {{
        btn.classList.toggle('active',
          (i === 0 && mode === 'en') ||
          (i === 1 && mode === 'both') ||
          (i === 2 && mode === 'zh'));
      }});
    }}
  </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✓ HTML 輸出：{output_path}")
    return str(output_path)
