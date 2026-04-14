from __future__ import annotations

import json
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, BATCH_SIZE, MODEL, OVERLAP_CUES
from segmenter import Cue

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_SEG_SECS = 35.0   # 超過這個秒數就強制拆段


def _split_if_overlong(cues: list[Cue]) -> list[list[Cue]]:
    """
    若一個 Claude 分組超過 MAX_SEG_SECS，按 ≤25 秒切成多段。
    優先在句尾（.?!）切割，逼不得已才在中間切。
    """
    if not cues:
        return []
    duration = cues[-1].end_sec - cues[0].start_sec
    if duration <= MAX_SEG_SECS:
        return [cues]

    chunks: list[list[Cue]] = []
    chunk: list[Cue] = []
    chunk_start = cues[0].start_sec

    for cue in cues:
        chunk.append(cue)
        elapsed = cue.end_sec - chunk_start
        is_sentence_end = cue.text.rstrip().endswith((".", "?", "!"))

        if (elapsed >= 25.0 and is_sentence_end) or elapsed >= MAX_SEG_SECS:
            chunks.append(chunk)
            chunk = []
            chunk_start = cue.end_sec

    if chunk:
        chunks.append(chunk)

    return chunks


def _translate_text(en: str, speaker: str = "Host") -> str:
    """單純翻譯英文段落（用於強制拆段後的補譯）。"""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": (
                f"請將以下英文翻譯成流暢的繁體中文，只回傳翻譯結果：\n\n{en}"
            ),
        }],
    )
    return next(b.text for b in response.content if b.type == "text").strip()


SYSTEM_PROMPT = """\
你是一個專業的英文 Podcast 翻譯助手。

任務：
1. 將【請處理以下 Cue】中的字幕行依照**語意完整性**分組成段落
   - 每段不超過 30 秒（以 Cue 的時間戳計算起訖）
   - 以語意完整為優先，不要在一個想法或句子中間強制切割
   - 每個 Cue 只能屬於一個段落，不能重複使用
   - 必須覆蓋所有 Cue，不能遺漏任何一個
2. 將每段英文翻譯成流暢的**繁體中文**
3. 依說話內容判斷說話者：
   - Host：主持人（主要提問、引導對話）
   - Guest：來賓（被採訪者、分享經驗與專業）
   - Narration：旁白、片頭片尾、廣告插播

**輸出規則（嚴格遵守）**：
- 【前段上下文】的 Cue 僅供理解語意，絕對不可出現在輸出的 "cues" 陣列中
- "cues" 陣列只填入【請處理以下 Cue】中出現的 Cue 編號（整數）
- 不要輸出時間戳，時間戳由程式從原始資料計算
- 第一個段落的第一個 cue 編號必須是本批次最小的編號

回傳**純 JSON 陣列**，不要有任何說明文字、markdown 或程式碼區塊：
[
  {
    "cues": [0, 1, 2],
    "zh": "段落繁體中文翻譯",
    "speaker": "Host 或 Guest 或 Narration"
  }
]
"""


def _cues_to_text(cues: list[Cue]) -> str:
    """格式：Cue {index} [{start} --> {end}] {text}"""
    return "\n".join(
        f"Cue {c.index} [{c.start} --> {c.end}] {c.text}"
        for c in cues
    )


def _parse_json_response(text: str) -> list[dict]:
    """
    從 Claude 回應中提取 JSON 陣列。
    用 raw_decode 從第一個 '[' 開始解析，遇到完整的 JSON 值就停止，
    不受後面多餘文字（說明、換行）影響，避免 'Extra data' 錯誤。
    """
    start = text.find("[")
    if start == -1:
        raise ValueError(f"回應中找不到 JSON 陣列：\n{text[:300]}")
    result, _ = json.JSONDecoder().raw_decode(text, start)
    return result


def _translate_batch(
    cues: list[Cue],
    context_cues: list[Cue] | None = None,
) -> list[dict]:
    """
    送一批 cues 給 Claude，讓它輸出「哪些 cue index 屬於哪個段落」。
    時間戳由本函式從原始 Cue 物件取得，不依賴 Claude 輸出，100% 精確。
    """
    # 建立 index → Cue 的對應表，只包含本批次的 cue
    cue_map = {c.index: c for c in cues}
    valid_indices = set(cue_map.keys())

    # 組合 prompt
    if context_cues:
        user_content = (
            f"【前段上下文，僅供理解語意，不納入輸出】\n"
            f"{_cues_to_text(context_cues)}\n\n"
            f"【請處理以下 Cue】\n"
            f"{_cues_to_text(cues)}"
        )
    else:
        user_content = f"【請處理以下 Cue】\n{_cues_to_text(cues)}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = next(b.text for b in response.content if b.type == "text")
    raw_segments = _parse_json_response(text)

    # 將 Claude 的 cue index 分組轉換成精確時間戳的段落
    segments: list[dict] = []
    covered: set[int] = set()

    for raw in raw_segments:
        # 過濾：只保留本批次合法的 index，且不重複
        indices = [
            i for i in raw.get("cues", [])
            if i in valid_indices and i not in covered
        ]
        if not indices:
            continue

        indices_sorted = sorted(indices)
        batch_cues = [cue_map[i] for i in indices_sorted]
        covered.update(indices_sorted)

        # 若 Claude 合出超長段落，強制拆段
        sub_groups = _split_if_overlong(batch_cues)
        if len(sub_groups) > 1:
            print(f"    ⚠ 段落過長（{batch_cues[-1].end_sec - batch_cues[0].start_sec:.0f}s），拆成 {len(sub_groups)} 段補譯")

        for sub_cues in sub_groups:
            en = " ".join(c.text for c in sub_cues)
            zh = raw.get("zh", "") if len(sub_groups) == 1 else _translate_text(en, raw.get("speaker", "Host"))
            segments.append({
                "start": sub_cues[0].start,
                "end":   sub_cues[-1].end,
                "en":    en,
                "zh":    zh,
                "speaker": raw.get("speaker", "Host"),
            })

    # 若有 cue 被 Claude 遺漏，把剩下的合併成一個 fallback 段落
    missed = sorted(valid_indices - covered)
    if missed:
        missed_cues = [cue_map[i] for i in missed]
        print(f"    ⚠ {len(missed)} 個 Cue 未被分配，合併為 fallback 段落")
        segments.append({
            "start": missed_cues[0].start,
            "end":   missed_cues[-1].end,
            "en":    " ".join(c.text for c in missed_cues),
            "zh":    "（翻譯缺漏）",
            "speaker": "Host",
        })

    # 按時間排序，確保輸出順序正確
    segments.sort(key=lambda s: s["start"])
    return segments


def translate(
    cues: list[Cue],
    video_id: str,
    cache_dir: str = "cache",
) -> list[dict]:
    """
    翻譯所有 cues，優先讀取 cache。
    回傳段落列表，每個段落包含 start / end / en / zh / speaker。
    時間戳直接從原始 SRT Cue 取得，不依賴 Claude 輸出。
    """
    Path(cache_dir).mkdir(exist_ok=True)
    cache_path = Path(cache_dir) / f"{video_id}.json"

    if cache_path.exists():
        print(f"  讀取 cache：{cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    total = len(cues)
    print(f"  共 {total} 條字幕，每批 {BATCH_SIZE} 條...")

    batches = [cues[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    results: list[dict] = []

    for i, batch in enumerate(batches):
        print(f"  批次 {i + 1}/{len(batches)} （cue {batch[0].index}–{batch[-1].index}）...")

        context = cues[max(0, i * BATCH_SIZE - OVERLAP_CUES) : i * BATCH_SIZE] if i > 0 else None

        try:
            segments = _translate_batch(batch, context_cues=context)
            results.extend(segments)
            print(f"    → 分組成 {len(segments)} 段，時間戳來自原始 SRT")
        except Exception as e:
            print(f"    ✗ 批次 {i + 1} 失敗：{e}")
            results.append({
                "start": batch[0].start,
                "end":   batch[-1].end,
                "en":    " ".join(c.text for c in batch),
                "zh":    "（翻譯失敗）",
                "speaker": "Host",
            })

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 儲存 cache：{cache_path}（共 {len(results)} 段）")
    return results
