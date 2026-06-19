import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
STORE_DIR = BASE_DIR / "store"
PROFILES_DIR = BASE_DIR / "profiles"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

for d in (UPLOADS_DIR, STORE_DIR / "documents", STORE_DIR / "profiles", STORE_DIR / "files"):
    d.mkdir(parents=True, exist_ok=True)
