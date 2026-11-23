"""
Quick Telegram Bot Connection Test (bot/test_telegram.py)
Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env and sends a test alert.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
from paper_bot import send_telegram

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env. "
            "Open .env with notepad and fill both fields first."
        )
    ok = send_telegram(
        "MODE: PAPER | TradingStock 一人 AI 交易台 Telegram 通知已接通！\n"
        "之后每日扫描、开仓/平仓提醒与风控警报会自动推送到这里。"
    )
    if ok:
        print("[SUCCESS] Test message sent to your Telegram!")
    else:
        raise RuntimeError("Telegram API returned an error. Double-check your token and chat_id, and make sure you clicked Start in your bot chat.")


if __name__ == "__main__":
    main()
