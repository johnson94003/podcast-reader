import os
from pathlib import Path
from dotenv import load_dotenv

# 明確指定 .env 的路徑（與 config.py 同一目錄）
load_dotenv(Path(__file__).parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-opus-4-6"
BATCH_SIZE = 80       # SRT cues per Claude call (~10-15 min of audio)
OVERLAP_CUES = 5      # cues from previous batch carried as context
