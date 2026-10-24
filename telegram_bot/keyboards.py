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
    legs_count: int = 1,
) -> InlineKeyboardMarkup:
    """Returns interactive action buttons for a proposed daily pick with SportyBet link and ticket mode toggling."""
    sporty_base = getattr(config, "SPORTYBET_BASE_URL", "https://www.sportybet.com/ng").rstrip("/")
    default_url = f"{sporty_base}/?shareCode={booking_code}" if booking_code else f"{sporty_base}/sport/basketball"
    fallback_label = "🏀 Open SportyBet Basketball"

    action_url = booking_url or default_url
    if booking_code and "shareCode=" not in action_url:
        action_url = f"{sporty_base}/?shareCode={booking_code}"
    action_label = f"🎟 Load Slip ({booking_code})" if booking_code else fallback_label

    if is_placed:
        decision_row = [
            InlineKeyboardButton("🔒 Bet Placed & Monitored", callback_data=f"bet_info_{bet_id}")
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
    else:
        decision_row = [
            InlineKeyboardButton("🎯 Bet Placed", callback_data=f"bet_placed_{bet_id}"),
            InlineKeyboardButton("🔄 Alternative Pick", callback_data=f"reroll_pick_{bet_id}"),
            InlineKeyboardButton("🗑️ Clear Bet", callback_data=f"bet_clear_{bet_id}"),
        ]

        if legs_count == 1:
            mode_toggle_row = [
                InlineKeyboardButton("🔀 Switch to 2-Leg Combo", callback_data=f"switch_mode_combo_{bet_id}")
            ]
        else:
            mode_toggle_row = [
                InlineKeyboardButton("🎯 Switch to 1-Leg Solo", callback_data=f"switch_mode_solo_{bet_id}")
            ]

        buttons = [
            decision_row,
            mode_toggle_row,
            [
                InlineKeyboardButton(action_label, url=action_url),
                InlineKeyboardButton("📊 View Balance", callback_data="view_balance"),
            ],
            [
                InlineKeyboardButton("📋 SportyBet Slip Helper", callback_data=f"get_helper_{bet_id}"),
            ]
        ]
    return InlineKeyboardMarkup(buttons)


def get_mode_selector_keyboard(current_mode: str = "auto") -> InlineKeyboardMarkup:
    """Returns interactive toggle buttons for choosing ticket structure."""
    mode = (current_mode or "auto").lower()
    solo_check = " ✅" if mode == "solo" else ""
    combo_check = " ✅" if mode == "combo" else ""
    auto_check = " ✅" if mode == "auto" else ""

    buttons = [
        [
            InlineKeyboardButton(f"🎯 1-Leg Solo Lock (1.50 - 1.60){solo_check}", callback_data="set_mode_solo"),
        ],
        [
            InlineKeyboardButton(f"🔀 2-Leg Safe Combo (1.50 - 1.99){combo_check}", callback_data="set_mode_combo"),
        ],
        [
            InlineKeyboardButton(f"⚖️ Auto-Balanced (Daily Smart Balance){auto_check}", callback_data="set_mode_auto"),
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
            InlineKeyboardButton("⚙️ Ticket Mode", callback_data="btn_ticket_mode"),
            InlineKeyboardButton("📈 30-Day Cycle Plan", callback_data="btn_cycle_plan"),
        ],
        [
            InlineKeyboardButton("🧹 Clear Memory", callback_data="btn_clear_memory"),
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
        ["⚙️ Ticket Mode", "📈 30-Day Cycle Plan"],
        ["🔄 Reroll Alternative", "🧹 Clear Memory"],
        ["❓ Help & Commands"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
