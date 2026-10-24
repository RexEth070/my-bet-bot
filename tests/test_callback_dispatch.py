"""Tests verifying that Telegram Bot commands gracefully handle CallbackQuery updates without update.message."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, CallbackQuery, Message

from core.ledger import LedgerDB
from telegram_bot.bot import TelegramBetBot


class TestCallbackDispatch(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ledger = MagicMock(spec=LedgerDB)
        self.agent = MagicMock()
        self.odds_api = MagicMock()
        self.bot = TelegramBetBot(ledger=self.ledger, agent=self.agent, odds_api=self.odds_api)

    async def test_today_pick_callback_target_resolution(self):
        """Verify today_pick_command resolves target message correctly from callback query when update.message is None."""
        user = MagicMock(spec=User)
        user.id = 5950295448

        mock_msg = MagicMock(spec=Message)
        mock_msg.reply_text = AsyncMock()

        query = MagicMock(spec=CallbackQuery)
        query.data = "btn_today_pick"
        query.message = mock_msg
        query.answer = AsyncMock()

        update = MagicMock(spec=Update)
        update.effective_user = user
        update.message = None  # Crucial: None in CallbackQueryUpdate!
        update.callback_query = query
        update.effective_message = mock_msg

        resolved = self.bot._get_target_message(update)
        self.assertEqual(resolved, mock_msg)

    async def test_callback_query_today_pick_dispatch(self):
        """Verify handle_callback_query dispatches btn_today_pick without AttributeError."""
        user = MagicMock(spec=User)
        user.id = 5950295448

        mock_msg = MagicMock(spec=Message)
        status_msg = MagicMock(spec=Message)
        status_msg.delete = AsyncMock()
        mock_msg.reply_text = AsyncMock(return_value=status_msg)

        query = MagicMock(spec=CallbackQuery)
        query.data = "btn_today_pick"
        query.message = mock_msg
        query.answer = AsyncMock()

        update = MagicMock(spec=Update)
        update.effective_user = user
        update.message = None
        update.callback_query = query
        update.effective_message = mock_msg

        context = MagicMock()
        context.application = MagicMock()

        # Mock predictions and ledger
        with patch.object(self.bot, "is_user_allowed", return_value=True), \
             patch.object(self.bot.odds_api, "get_upcoming_fixtures_summary", new_callable=AsyncMock) as mock_fixtures, \
             patch.object(self.bot.agent, "analyze_and_predict", new_callable=AsyncMock) as mock_predict, \
             patch.object(self.bot.ledger, "get_or_create_user") as mock_user, \
             patch.object(self.bot.ledger, "get_proposed_bet", return_value=None), \
             patch.object(self.bot.ledger, "record_bet", return_value=999):

            user_state = MagicMock()
            user_state.current_day = 1
            user_state.current_balance = 500.0
            mock_user.return_value = user_state

            prediction = MagicMock()
            prediction.selections = []
            prediction.combined_odds = 1.55
            prediction.suggested_stake = 500.0
            prediction.booking_code = "ABC12"
            prediction.booking_url = "https://sportybet.com"
            mock_predict.return_value = prediction
            mock_fixtures.return_value = "Sample fixtures"

            await self.bot.handle_callback_query(update, context)

            query.answer.assert_called()
            mock_msg.reply_text.assert_called()

    async def test_split_telegram_message(self):
        """Verify long message splitting under 3900 characters."""
        from telegram_bot.bot import split_telegram_message

        short_msg = "Hello World"
        self.assertEqual(split_telegram_message(short_msg), ["Hello World"])

        long_msg = ("A" * 2500) + "\n\n" + ("B" * 2500)
        chunks = split_telegram_message(long_msg, max_chunk_size=3000)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= 3000 for c in chunks))
        self.assertEqual(chunks[0], "A" * 2500)
        self.assertEqual(chunks[1], "B" * 2500)

    async def test_send_safe_telegram_message_splits_and_attaches_markup(self):
        """Verify send_safe_telegram_message splits large text and puts markup on the final chunk."""
        from telegram_bot.bot import send_safe_telegram_message

        mock_target = MagicMock(spec=Message)
        mock_target.reply_text = AsyncMock()

        long_text = ("Part 1 " * 400) + "\n\n" + ("Part 2 " * 400)
        markup = MagicMock()

        await send_safe_telegram_message(
            target=mock_target,
            text=long_text,
            parse_mode="Markdown",
            reply_markup=markup,
            max_chunk_size=2000,
        )

        self.assertGreaterEqual(mock_target.reply_text.call_count, 2)
        # Verify final call had the reply_markup
        last_call_args = mock_target.reply_text.call_args_list[-1]
        self.assertEqual(last_call_args.kwargs["reply_markup"], markup)

    async def test_send_safe_telegram_message_markdown_fallback(self):
        """Verify send_safe_telegram_message falls back to parse_mode=None on entity error."""
        from telegram_bot.bot import send_safe_telegram_message

        mock_target = MagicMock(spec=Message)
        # First call fails (bad markdown), second call succeeds (plain text)
        mock_target.reply_text = AsyncMock(side_effect=[Exception("Can't parse entities"), MagicMock()])

        await send_safe_telegram_message(
            target=mock_target,
            text="Unclosed *markdown tag",
            parse_mode="Markdown",
        )

        self.assertEqual(mock_target.reply_text.call_count, 2)
        # Second attempt should have parse_mode=None
        self.assertIsNone(mock_target.reply_text.call_args_list[1].kwargs["parse_mode"])

