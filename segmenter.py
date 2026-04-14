from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Cue:
    index: int
    start: str      # "HH:MM:SS,mmm"
    end: str
    text: str
    start_sec: float
    end_sec: float


def time_to_seconds(t: str) -> float:
    """'HH:MM:SS,mmm' → float seconds"""
    t = t.strip()
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(srt_path: str) -> list[Cue]:
    """
    解析 SRT 檔案，回傳 Cue 列表。
    每個 Cue 是原始的一條字幕行，帶時間戳。
    語意分組交給 Claude。
    """
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # 分割成字幕塊（空行為分隔）
    blocks = re.split(r"\n\s*\n", content.strip())
    cues: list[Cue] = []

    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        # 找時間戳行
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue

        try:
            start_raw, end_raw = ts_line.split("-->")
            start_raw = start_raw.strip()
            end_raw = end_raw.strip()

            # 取時間戳之後的所有行作為文字
            ts_idx = lines.index(ts_line)
            text_lines = lines[ts_idx + 1:]
            text = " ".join(text_lines)

            # 移除 HTML 標籤（<i>, <b> 等）和 [音效] 標記
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\[.*?\]", "", text)
            text = text.strip()

            if not text:
                continue

            cues.append(Cue(
                index=len(cues),
                start=start_raw,
                end=end_raw,
                text=text,
                start_sec=time_to_seconds(start_raw),
                end_sec=time_to_seconds(end_raw),
            ))
        except Exception as e:
            # 跳過格式錯誤的塊
            continue

    return cues
