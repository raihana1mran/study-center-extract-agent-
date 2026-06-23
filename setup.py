# -*- coding: utf-8 -*-
"""
setup.py -- One-command project setup script.

Handles:
  1. Install Python dependencies
  2. Install Python dependencies
  3. Install Playwright browsers
  4. Copy .env.example → .env (if not exists)
  5. Verify PostgreSQL connection
  6. Initialise database tables

Run once: python setup.py
"""

import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent


def run(cmd, check=True, shell=True):
    print(f"  >> {cmd}")
    result = subprocess.run(cmd, shell=shell, check=check)
    return result


def main():
    print("\n" + "=" * 60)
    print("  NIOS Study Centre Agent — Setup")
    print("=" * 60 + "\n")

    python = sys.executable

    # ── 1. Install dependencies ──
    print("[*] Installing Python packages...")
    run(f'"{python}" -m pip install --upgrade pip -q')
    run(f'"{python}" -m pip install -r requirements.txt -q')
    print("  [OK] Packages installed.\n")

    # ── 2. Install Playwright browsers ──
    print("[*] Installing Playwright Chromium browser...")
    run(f'"{python}" -m playwright install chromium')
    print("  [OK] Playwright ready.\n")

    # ── 3. Copy .env.example -> .env ──
    env_file    = BASE_DIR / ".env"
    env_example = BASE_DIR / ".env.example"

    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print("[*] Created .env from .env.example")
        print("  [!] Please edit .env and add your:")
        print("     - OPENROUTER_API_KEY  (from https://openrouter.ai)")
        print("     - DATABASE_URL        (your PostgreSQL connection string)")
        print()
    elif env_file.exists():
        print("  [OK] .env already exists (skipped)\n")
    else:
        print("  [!] No .env.example found -- please create .env manually.\n")

    # ── 4. Test DB & init tables ──
    print("[*] Connecting to PostgreSQL and creating tables...")
    try:
        sys.path.insert(0, str(BASE_DIR))
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")

        from db.database import init_db
        init_db()
        print("  [OK] Database tables ready.\n")
    except Exception as e:
        print(f"  [!] Database setup failed: {e}")
        print("     Please check DATABASE_URL in your .env file.")
        print("     You can run database setup later with:")
        print("       python -c \"from db.database import init_db; init_db()\"\n")

    print("=" * 60)
    print("  [DONE] Setup complete!")
    print()
    print("  Next steps:")
    print("   1. Edit .env - add OPENROUTER_API_KEY and DATABASE_URL")
    print("   2. Test run:      python main.py --test")
    print("   3. Full run:      python main.py")
    print("   4. With schedule: python main.py --schedule")
    print("   5. Reports only:  python main.py --reports-only")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
