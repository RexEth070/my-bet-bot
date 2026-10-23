"""Interactive Telegram Keyboards and Inline Buttons."""

from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

import config


def get_pick_action_keyboard(
    bet_id: int,
    sport: str = "basketball",
    booking_url: Optional[str] = None,
    booking_code: Optional[str] = None,
    is_placed: bool = False,
) -> InlineKeyboardMarkup:
    """Returns interactive action buttons for a proposed daily pick with SportyBet link."""
    sporty_base = getattr(config, "SPORTYBET_BASE_URL", "https://www.sportybet.com/ng").rstrip("/")
    default_url = f"{sporty_base}/sport/basketball"
    fallback_label = "🏀 Open SportyBet Basketball"

    action_url = booking_url or default_url
    action_label = f"🎟 Load Slip ({booking_code})" if booking_code else fallback_label

    if is_placed:
        decision_row = [
            InlineKeyboardButton("🔒 Bet Placed & Monitored", callback_data=f"bet_info_{bet_id}")
        ]
    else:
        decision_row = [
            InlineKeyboardButton("🎯 Bet Placed", callback_data=f"bet_placed_{bet_id}"),
            InlineKeyboardButton("🔄 Alternative Pick", callback_data=f"reroll_pick_{bet_id}"),
            InlineKeyboardButton("🗑️ Clear Bet", callback_data=f"bet_clear_{bet_id}"),
        ]

    buttons = [
        decision_row,
        [
            InlineKeyboardButton(action_label, url=action_url),
            InlineKeyboardButton("📊 View Balance", callback_data="view_balance"),
        ],
        [
            InlineKeyboardButton("📋 SportyBet Slip Helper", callback_data=f"get_helper_{bet_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_nba_strategy_keyboard() -> InlineKeyboardMarkup:
    """Returns quick action buttons for NBA Totals strategy."""
    buttons = [
        [
            InlineKeyboardButton("🎯 Today's Pick", callback_data="btn_today_pick"),
            InlineKeyboardButton("📊 Win-Rate Stats", callback_data="view_stats"),
        ],
        [
            InlineKeyboardButton("🧹 Clear Memory", callback_data="btn_clear_memory"),
            InlineKeyboardButton("📈 30-Day Cycle Plan", callback_data="btn_cycle_plan"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_sport_selector_keyboard(current_sport: str = "basketball") -> InlineKeyboardMarkup:
    """Returns locked NBA sport mode badge keyboard."""
    buttons = [
        [
            InlineKeyboardButton("✅ 🏀 NBA Basketball (Totals Locked)", callback_data="nba_locked_info"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent quick-action keyboard."""
    keyboard = [
        ["🎯 Today's Pick", "💰 My Balance"],
        ["📊 Win-Rate Stats", "🏀 NBA Strategy"],
        ["📈 30-Day Cycle Plan", "📜 Recent Bets"],
        ["🔄 Reroll Alternative", "🧹 Clear Memory"],
        ["❓ Help & Commands"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
