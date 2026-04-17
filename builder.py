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

    /* ── Auto-advance toggle ── */
    #auto-btn {{
      padding: 5px 11px;
      border: 1px solid #ccc;
      border-radius: 14px;
      background: white;
      font-size: 12px;
      cursor: pointer;
      color: #aaa;
      transition: all 0.15s;
      flex-shrink: 0;
      white-space: nowrap;
    }}
    #auto-btn.on {{
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

    /* ── Read progress ── */
    .segment.read {{
      background: #f0ece4;
    }}

    /* ── Auth widget ── */
    #auth-widget {{
      position: relative;
      flex-shrink: 0;
    }}
    #auth-btn {{
      padding: 5px 12px;
      border: 1px solid #ccc;
      border-radius: 14px;
      background: white;
      font-size: 12px;
      cursor: pointer;
      color: #555;
      transition: all 0.15s;
    }}
    #auth-btn.on {{
      background: #2d6a4f;
      border-color: #2d6a4f;
      color: white;
    }}
    #auth-panel {{
      display: none;
      position: absolute;
      right: 0;
      top: 38px;
      background: white;
      border: 1px solid #ddd;
      border-radius: 14px;
      padding: 16px;
      width: 230px;
      box-shadow: 0 6px 20px rgba(0,0,0,0.12);
      z-index: 300;
    }}
    #auth-panel input {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid #ddd;
      border-radius: 8px;
      font-size: 13px;
      margin-bottom: 8px;
      outline: none;
    }}
    #auth-panel input:focus {{ border-color: #2d6a4f; }}
    .auth-submit {{
      width: 100%;
      padding: 8px;
      background: #2d6a4f;
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 13px;
      cursor: pointer;
    }}
    .auth-submit.danger {{ background: #c0392b; }}
    #auth-msg {{
      font-size: 12px;
      color: #888;
      text-align: center;
      margin-bottom: 10px;
      min-height: 16px;
    }}

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
    <button id="auto-btn" class="on" onclick="toggleAutoAdvance()" title="連播：播完自動接下一段">▶▶ 連播</button>
    <div id="auth-widget">
      <button id="auth-btn" onclick="toggleAuthPanel()">登入</button>
      <div id="auth-panel">
        <div id="auth-form-area">
          <div id="auth-msg">登入以同步閱讀進度</div>
          <input type="email"    id="auth-email" placeholder="Email">
          <input type="password" id="auth-pw"    placeholder="密碼"
                 onkeydown="if(event.key==='Enter')doLogin()">
          <button class="auth-submit" onclick="doLogin()">登入 / 註冊</button>
        </div>
        <div id="auth-user-area" style="display:none">
          <div id="auth-msg"></div>
          <button class="auth-submit danger" onclick="doLogout()">登出</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Transcript ── -->
  <div id="transcript">
{segments_html}
  </div>

  <!-- ── Supabase ── -->
  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>

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
    let autoAdvance  = true;   // 連播模式（播完自動接下一段）

    function toggleAutoAdvance() {{
      autoAdvance = !autoAdvance;
      const btn = document.getElementById('auto-btn');
      btn.classList.toggle('on', autoAdvance);
    }}

    function playNext(fromIdx) {{
      if (fromIdx === null || fromIdx + 1 >= segs.length) return false;
      const nextSeg   = segs[fromIdx + 1];
      const nextStart = parseFloat(nextSeg.dataset.start);
      const nextEnd   = parseFloat(nextSeg.dataset.end);
      _loadSeg(fromIdx + 1, nextStart, nextEnd);
      nextSeg.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      return true;
    }}

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
        const doneIdx = activeIdx;
        activeIdx    = null;
        stopTicker();
        segs.forEach(s => s.classList.remove('playing'));
        resetAllSegs();
        if (autoAdvance && playNext(doneIdx)) return;

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
      markRead(idx);        // 記錄已讀，同步到 Supabase
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
        // 播完：清空所有狀態，視情況連播或停止
        segStart     = null;
        segEnd       = null;
        activeSegEnd = null;
        const doneIdx = activeIdx;
        activeIdx    = null;          // 清空後 PAUSED 事件不會誤判為繼續
        if (doneIdx !== null) setSegState(doneIdx, 'idle');
        segs.forEach(s => s.classList.remove('playing'));
        if (autoAdvance && playNext(doneIdx)) return;  // 連播：接下一段
        player.pauseVideo();                           // 非連播：停住
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

    // ── Supabase 閱讀進度同步 ────────────────────────────
    const SB_URL = 'https://bxrcntccrglfxfyabcrc.supabase.co';
    const SB_KEY = 'sb_publishable_w7wT56HTe8E-s3gABzuvew_7FsDKHSD';
    let sb = null, sbUser = null, readSet = new Set();

    window.addEventListener('load', async () => {{
      const {{ createClient }} = window.supabase;
      sb = createClient(SB_URL, SB_KEY);
      const {{ data: {{ user }} }} = await sb.auth.getUser();
      if (user) {{ sbUser = user; await loadProgress(); renderAuth(); }}
      sb.auth.onAuthStateChange(async (_, session) => {{
        sbUser = session?.user ?? null;
        renderAuth();
        if (sbUser) await loadProgress(); else clearReadUI();
      }});
    }});

    async function loadProgress() {{
      if (!sbUser) return;
      const {{ data: rows, error }} = await sb.from('reading_progress')
        .select('read_segments,last_segment')
        .eq('video_id', VIDEO_ID)
        .order('updated_at', {{ ascending: false }})
        .limit(1);
      if (error || !rows || rows.length === 0) return;
      const data = rows[0];
      readSet = new Set((data.read_segments || []).map(Number));
      readSet.forEach(i => document.getElementById('seg-'+i)?.classList.add('read'));
      if (data.last_segment != null) {{
        const el = document.getElementById('seg-' + data.last_segment);
        if (el) setTimeout(() => el.scrollIntoView({{behavior:'smooth',block:'center'}}), 600);
      }}
    }}

    function markRead(idx) {{
      if (!sbUser) return;
      readSet.add(idx);
      document.getElementById('seg-'+idx)?.classList.add('read');
      sb.from('reading_progress').upsert({{
        user_id: sbUser.id, video_id: VIDEO_ID,
        read_segments: [...readSet], last_segment: idx,
        updated_at: new Date().toISOString()
      }}, {{ onConflict: 'user_id,video_id' }});
    }}

    function clearReadUI() {{
      document.querySelectorAll('.segment.read').forEach(el => el.classList.remove('read'));
      readSet.clear();
    }}

    function toggleAuthPanel() {{
      const p = document.getElementById('auth-panel');
      p.style.display = p.style.display === 'block' ? 'none' : 'block';
    }}

    function renderAuth() {{
      const btn   = document.getElementById('auth-btn');
      const form  = document.getElementById('auth-form-area');
      const user  = document.getElementById('auth-user-area');
      const msg   = document.getElementById('auth-msg');
      if (sbUser) {{
        btn.textContent = '✓ 已同步';
        btn.classList.add('on');
        form.style.display = 'none';
        user.style.display = 'block';
        msg.textContent = sbUser.email;
      }} else {{
        btn.textContent = '登入';
        btn.classList.remove('on');
        form.style.display = 'block';
        user.style.display = 'none';
      }}
    }}

    async function doLogin() {{
      const email = document.getElementById('auth-email').value.trim();
      const pw    = document.getElementById('auth-pw').value;
      const msg   = document.getElementById('auth-msg');
      msg.textContent = '登入中...';
      const {{ error }} = await sb.auth.signInWithPassword({{ email, password: pw }});
      if (error) {{
        const {{ error: e2 }} = await sb.auth.signUp({{ email, password: pw }});
        msg.textContent = e2 ? '失敗：' + error.message : '已建立帳號，請登入';
      }} else {{
        document.getElementById('auth-panel').style.display = 'none';
      }}
    }}

    async function doLogout() {{
      await sb.auth.signOut();
      document.getElementById('auth-panel').style.display = 'none';
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


def build_index_html(
    cache_dir: str = "cache",
    output_dir: str = "output",
) -> str:
    """
    掃描 cache/*.meta.json，生成 output/index.html 影片清單首頁。
    依 upload_date 倒序排列（最新在最上面）。
    """
    cache_path  = Path(cache_dir)
    output_path = Path(output_dir) / "index.html"
    Path(output_dir).mkdir(exist_ok=True)

    # 收集所有已處理影片的 meta
    videos = []
    for meta_file in sorted(cache_path.glob("*.meta.json")):
        vid = meta_file.stem.replace(".meta", "")
        html_file = Path(output_dir) / f"{vid}.html"
        if not html_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        videos.append({
            "id":      vid,
            "title":   meta.get("title", vid),
            "channel": meta.get("channel", ""),
        })

    # 生成卡片 HTML
    def card(v):
        def esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""    <a class="card" href="{v['id']}.html">
      <div class="card-title">{esc(v['title'])}</div>
      <div class="card-channel">{esc(v['channel'])}</div>
    </a>"""

    cards_html = "\n".join(card(v) for v in videos)
    count = len(videos)

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Podcast Reader</title>
  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f5f0e8;
      color: #2c2c2c;
      min-height: 100vh;
    }}
    header {{
      background: #fffdf8;
      border-bottom: 1px solid #ddd5c4;
      padding: 24px 20px 20px;
      text-align: center;
      position: relative;
    }}
    header h1 {{
      font-size: 22px;
      font-weight: 700;
      color: #2d6a4f;
      letter-spacing: -0.3px;
    }}
    header p {{
      font-size: 13px;
      color: #aaa;
      margin-top: 4px;
    }}
    .list {{
      max-width: 680px;
      margin: 28px auto;
      padding: 0 16px 60px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .card {{
      display: block;
      background: white;
      border-radius: 14px;
      padding: 18px 20px;
      text-decoration: none;
      color: inherit;
      border: 2px solid transparent;
      transition: border-color 0.18s, box-shadow 0.18s;
    }}
    .card:hover {{
      border-color: #2d6a4f;
      box-shadow: 0 4px 16px rgba(45,106,79,0.10);
    }}
    .card-title {{
      font-size: 15px;
      font-weight: 600;
      line-height: 1.4;
      color: #1a1a1a;
    }}
    .card-channel {{
      font-size: 12px;
      color: #aaa;
      margin-top: 5px;
    }}
    .empty {{
      text-align: center;
      color: #aaa;
      font-size: 14px;
      padding: 60px 0;
    }}
    /* ── Auth widget ── */
    #auth-widget {{
      position: absolute;
      top: 16px;
      right: 16px;
    }}
    #auth-btn {{
      background: #eee7d9;
      border: none;
      border-radius: 8px;
      padding: 6px 14px;
      font-size: 13px;
      cursor: pointer;
      color: #555;
      font-family: inherit;
      transition: background 0.15s;
    }}
    #auth-btn:hover {{ background: #e0d8cc; }}
    #auth-btn.on {{ background: #d4edda; color: #2d6a4f; font-weight: 600; }}
    #auth-panel {{
      display: none;
      position: absolute;
      right: 0;
      top: 36px;
      background: white;
      border: 1px solid #ddd;
      border-radius: 12px;
      padding: 16px;
      width: 240px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.12);
      z-index: 100;
      text-align: left;
    }}
    #auth-panel input {{
      width: 100%;
      border: 1px solid #ddd;
      border-radius: 7px;
      padding: 7px 10px;
      font-size: 13px;
      margin-bottom: 8px;
      font-family: inherit;
      outline: none;
    }}
    #auth-panel input:focus {{ border-color: #2d6a4f; }}
    #auth-panel button {{
      width: 100%;
      padding: 8px;
      border: none;
      border-radius: 7px;
      font-size: 13px;
      cursor: pointer;
      font-family: inherit;
    }}
    #auth-login-btn {{ background: #2d6a4f; color: white; }}
    #auth-login-btn:hover {{ background: #235c42; }}
    #auth-logout-btn {{ background: #f0ece4; color: #555; margin-top: 8px; }}
    #auth-logout-btn:hover {{ background: #e0dcd4; }}
    #auth-msg {{ font-size: 12px; color: #888; margin-top: 8px; word-break: break-all; }}
  </style>
</head>
<body>
  <header>
    <h1>🎙 Podcast Reader</h1>
    <p>共 {count} 支雙語逐字稿</p>
    <div id="auth-widget">
      <button id="auth-btn" onclick="toggleAuthPanel()">登入</button>
      <div id="auth-panel">
        <div id="auth-form-area">
          <input id="auth-email" type="email" placeholder="Email" autocomplete="email">
          <input id="auth-pw" type="password" placeholder="密碼（6 位以上）" autocomplete="current-password">
          <button id="auth-login-btn" onclick="doLogin()">登入 / 註冊</button>
        </div>
        <div id="auth-user-area" style="display:none">
          <button id="auth-logout-btn" onclick="doLogout()">登出</button>
        </div>
        <div id="auth-msg"></div>
      </div>
    </div>
  </header>
  <div class="list">
{"    <p class='empty'>還沒有影片，請等待自動更新。</p>" if not videos else cards_html}
  </div>
  <script>
    const SB_URL = 'https://bxrcntccrglfxfyabcrc.supabase.co';
    const SB_KEY = 'sb_publishable_w7wT56HTe8E-s3gABzuvew_7FsDKHSD';
    let sb = null, sbUser = null;

    window.addEventListener('load', async () => {{
      const {{ createClient }} = window.supabase;
      sb = createClient(SB_URL, SB_KEY);
      const {{ data: {{ user }} }} = await sb.auth.getUser();
      if (user) {{ sbUser = user; renderAuth(); }}
      sb.auth.onAuthStateChange((_, session) => {{
        sbUser = session?.user ?? null;
        renderAuth();
      }});
    }});

    function toggleAuthPanel() {{
      const p = document.getElementById('auth-panel');
      p.style.display = p.style.display === 'block' ? 'none' : 'block';
    }}

    function renderAuth() {{
      const btn  = document.getElementById('auth-btn');
      const form = document.getElementById('auth-form-area');
      const user = document.getElementById('auth-user-area');
      const msg  = document.getElementById('auth-msg');
      if (sbUser) {{
        btn.textContent = '✓ 已登入';
        btn.classList.add('on');
        form.style.display = 'none';
        user.style.display = 'block';
        msg.textContent = sbUser.email;
      }} else {{
        btn.textContent = '登入';
        btn.classList.remove('on');
        form.style.display = 'block';
        user.style.display = 'none';
        msg.textContent = '';
      }}
    }}

    async function doLogin() {{
      const email = document.getElementById('auth-email').value.trim();
      const pw    = document.getElementById('auth-pw').value;
      const msg   = document.getElementById('auth-msg');
      msg.textContent = '登入中...';
      const {{ error }} = await sb.auth.signInWithPassword({{ email, password: pw }});
      if (error) {{
        const {{ error: e2 }} = await sb.auth.signUp({{ email, password: pw }});
        msg.textContent = e2 ? '失敗：' + error.message : '已建立帳號，請重新登入';
      }} else {{
        document.getElementById('auth-panel').style.display = 'none';
      }}
    }}

    async function doLogout() {{
      await sb.auth.signOut();
      document.getElementById('auth-panel').style.display = 'none';
    }}
  </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✓ 首頁輸出：{output_path}（{count} 支影片）")
    return str(output_path)
