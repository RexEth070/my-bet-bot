"""Interactive Telegram Keyboards and Inline Buttons."""

from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


import config


def get_pick_action_keyboard(
    bet_id: int,
    sport: str = "football",
    booking_url: Optional[str] = None,
    booking_code: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Returns interactive action buttons for a proposed daily pick with SportyBet link."""
    sporty_base = getattr(config, "SPORTYBET_BASE_URL", "https://www.sportybet.com/ng").rstrip("/")
    if "basket" in str(sport).lower():
        default_url = f"{sporty_base}/sport/basketball"
    else:
        default_url = f"{sporty_base}/sport/football"

    action_url = booking_url or default_url
    action_label = f"🎟 Load Slip ({booking_code})" if booking_code else "⚽ Open SportyBet"

    buttons = [
        [
            InlineKeyboardButton("✅ Mark Won", callback_data=f"outcome_won_{bet_id}"),
            InlineKeyboardButton("❌ Mark Lost", callback_data=f"outcome_lost_{bet_id}"),
        ],
        [
            InlineKeyboardButton(action_label, url=action_url),
            InlineKeyboardButton("📊 View Balance", callback_data="view_balance"),
        ],
        [
            InlineKeyboardButton("📋 SportyBet Slip Helper", callback_data=f"get_helper_{bet_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent quick-action keyboard."""
    keyboard = [
        ["🎯 Today's Pick", "💰 My Balance"],
        ["📈 30-Day Cycle Plan", "📜 Recent Bets"],
        ["❓ Help & Commands"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
