import os
from pathlib import Path

# Check what dotenv actually is and whether it has load_dotenv
try:
    import dotenv
    print("dotenv module file:", getattr(dotenv, "__file__", "?"))
    print("has load_dotenv:", hasattr(dotenv, "load_dotenv"))
except ImportError:
    print("dotenv NOT installed")

import config
print("XAI after config import:", bool(os.environ.get("XAI_API_KEY")))

for p in (Path("C:/ClaudeVision/.env"), Path("C:/ClaudeVision/src/.env"), Path.cwd()/".env"):
    print(p, "->", "EXISTS" if p.exists() else "missing")

for p in (Path("C:/ClaudeVision/.env"), Path("C:/ClaudeVision/src/.env")):
    if p.exists():
        print(f"--- keys in {p} ---")
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                print("   ", line.split("=",1)[0].strip())
