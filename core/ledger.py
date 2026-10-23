"""SQLite Ledger Database Engine for tracking 30-Day Challenge and Bankroll."""

import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from core.models import LedgerState, BetRecord
from core.compound_math import calculate_next_day_state
import config


def get_current_time_iso() -> str:
    """Returns timezone-aware ISO formatted string."""
    return datetime.now(timezone.utc).isoformat()


class LedgerDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DB_PATH
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager that ensures the SQLite connection is always closed."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initializes tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    current_day INTEGER DEFAULT 1,
                    current_balance REAL DEFAULT 500.0,
                    initial_stake REAL DEFAULT 500.0,
                    total_withdrawn REAL DEFAULT 0.0,
                    total_won_bets INTEGER DEFAULT 0,
                    total_lost_bets INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    highest_streak INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'ACTIVE',
                    updated_at TEXT
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    day_number INTEGER,
                    event_name TEXT,
                    market TEXT,
                    selection TEXT,
                    odds REAL,
                    stake REAL,
                    potential_return REAL,
                    outcome TEXT DEFAULT 'PENDING',
                    profit_loss REAL DEFAULT 0.0,
                    created_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id)
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    day_number INTEGER,
                    amount REAL,
                    status TEXT DEFAULT 'LOGGED',
                    created_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id)
                );
            """)

            # Ensure booking columns exist
            try:
                cursor.execute("ALTER TABLE bets ADD COLUMN booking_code TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE bets ADD COLUMN booking_url TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE user_profiles ADD COLUMN preferred_sport TEXT DEFAULT 'basketball'")
            except sqlite3.OperationalError:
                pass

            conn.commit()

    def get_or_create_user(self, user_id: int, initial_stake: Optional[float] = None) -> LedgerState:
        """Retrieves user profile or initializes a fresh one."""
        if initial_stake is None:
            initial_stake = config.DEFAULT_INITIAL_STAKE
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            now = get_current_time_iso()

            if not row:
                cursor.execute("""
                    INSERT INTO user_profiles (
                        user_id, current_day, current_balance, initial_stake,
                        total_withdrawn, total_won_bets, total_lost_bets,
                        current_streak, highest_streak, status, updated_at
                    ) VALUES (?, 1, ?, ?, 0.0, 0, 0, 0, 0, 'ACTIVE', ?)
                """, (user_id, initial_stake, initial_stake, now))
                conn.commit()
                return LedgerState(
                    user_id=user_id,
                    current_day=1,
                    current_balance=initial_stake,
                    initial_stake=initial_stake,
                    total_withdrawn=0.0,
                    total_won_bets=0,
                    total_lost_bets=0,
                    current_streak=0,
                    highest_streak=0,
                    status="ACTIVE",
                    updated_at=now,
                )

            return LedgerState(
                user_id=row["user_id"],
                current_day=row["current_day"],
                current_balance=row["current_balance"],
                initial_stake=row["initial_stake"],
                total_withdrawn=row["total_withdrawn"],
                total_won_bets=row["total_won_bets"],
                total_lost_bets=row["total_lost_bets"],
                current_streak=row["current_streak"],
                highest_streak=row["highest_streak"],
                status=row["status"],
                updated_at=row["updated_at"],
            )

    def record_bet(self, user_id: int, bet: BetRecord) -> int:
        """Stores a newly proposed/placed bet."""
        now = get_current_time_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bets (
                    user_id, day_number, event_name, market, selection,
                    odds, stake, potential_return, outcome, profit_loss,
                    booking_code, booking_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                bet.day_number,
                bet.event_name,
                bet.market,
                bet.selection,
                bet.odds,
                bet.stake,
                bet.potential_return,
                bet.outcome,
                bet.profit_loss,
                getattr(bet, "booking_code", None),
                getattr(bet, "booking_url", None),
                now,
            ))
            conn.commit()
            return cursor.lastrowid

    def log_bet_outcome(
        self,
        user_id: int,
        won: bool,
        bet_id: Optional[int] = None,
        actual_odds: Optional[float] = None,
        actual_payout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Processes a match outcome (WON / LOST) and updates the user's ledger."""
        state = self.get_or_create_user(user_id)
        odds = actual_odds or config.TARGET_DAILY_ODDS

        # Calculate math transition
        transition = calculate_next_day_state(
            current_day=state.current_day,
            current_balance=state.current_balance,
            won=won,
            actual_odds=odds,
            cycle_days=config.WITHDRAWAL_CYCLE_DAYS,
            withdrawal_pct=config.WITHDRAWAL_PERCENTAGE,
            actual_payout=actual_payout,
        )

        now = get_current_time_iso()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Update latest placed/pending bet if bet_id not given
            if bet_id:
                cursor.execute("""
                    UPDATE bets SET outcome = ?, profit_loss = ?
                    WHERE id = ? AND user_id = ?
                """, ("WON" if won else "LOST", transition["profit_loss"], bet_id, user_id))
            else:
                cursor.execute("""
                    UPDATE bets SET outcome = ?, profit_loss = ?
                    WHERE id = (
                        SELECT id FROM bets WHERE user_id = ? AND outcome IN ('PLACED', 'PENDING')
                        ORDER BY id DESC LIMIT 1
                    )
                """, ("WON" if won else "LOST", transition["profit_loss"], user_id))

            # Update withdrawal record if applicable
            new_total_withdrawn = state.total_withdrawn
            if transition["is_withdrawal_day"] and transition["withdrawal_amount"] > 0:
                new_total_withdrawn = round(new_total_withdrawn + transition["withdrawal_amount"], 2)
                cursor.execute("""
                    INSERT INTO withdrawals (user_id, day_number, amount, status, created_at)
                    VALUES (?, ?, ?, 'LOGGED', ?)
                """, (user_id, state.current_day, transition["withdrawal_amount"], now))

            # Update user stats
            new_streak = state.current_streak + 1 if won else 0
            highest_streak = max(state.highest_streak, new_streak)
            won_count = state.total_won_bets + (1 if won else 0)
            lost_count = state.total_lost_bets + (0 if won else 1)

            # Cap day at 30 or reset/continue
            next_day = transition["next_day"]
            new_status = "COMPLETED" if next_day > config.TOTAL_CHALLENGE_DAYS else "ACTIVE"

            cursor.execute("""
                UPDATE user_profiles
                SET current_day = ?,
                    current_balance = ?,
                    total_withdrawn = ?,
                    total_won_bets = ?,
                    total_lost_bets = ?,
                    current_streak = ?,
                    highest_streak = ?,
                    status = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (
                next_day,
                transition["new_balance"],
                new_total_withdrawn,
                won_count,
                lost_count,
                new_streak,
                highest_streak,
                new_status,
                now,
                user_id,
            ))
            conn.commit()

        transition["total_withdrawn_overall"] = new_total_withdrawn
        transition["streak"] = new_streak
        return transition

    def confirm_bet_placed(self, user_id: int, bet_id: int) -> Optional[BetRecord]:
        """Marks a proposed bet as PLACED (active tracking) and clears any other PROPOSED bets."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Clear other unplaced PROPOSED bets for this user to avoid stale picks
            cursor.execute("""
                UPDATE bets SET outcome = 'CLEARED'
                WHERE user_id = ? AND outcome = 'PROPOSED' AND id != ?
            """, (user_id, bet_id))

            # Mark this specific bet as PLACED
            cursor.execute("""
                UPDATE bets SET outcome = 'PLACED'
                WHERE id = ? AND user_id = ?
            """, (bet_id, user_id))
            conn.commit()

        return self.get_bet_by_id(bet_id, user_id)

    def clear_bet(self, user_id: int, bet_id: int) -> bool:
        """Clears/discards a proposed prediction from memory so it will not be tracked or graded."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE bets SET outcome = 'CLEARED'
                WHERE id = ? AND user_id = ?
            """, (bet_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_bet_by_id(self, bet_id: int, user_id: Optional[int] = None) -> Optional[BetRecord]:
        """Fetches a single BetRecord by id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("SELECT * FROM bets WHERE id = ? AND user_id = ?", (bet_id, user_id))
            else:
                cursor.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return BetRecord(
                id=r["id"],
                day_number=r["day_number"],
                event_name=r["event_name"],
                market=r["market"],
                selection=r["selection"],
                odds=r["odds"],
                stake=r["stake"],
                potential_return=r["potential_return"],
                outcome=r["outcome"],
                profit_loss=r["profit_loss"],
                booking_code=r["booking_code"] if "booking_code" in r.keys() else None,
                booking_url=r["booking_url"] if "booking_url" in r.keys() else None,
                created_at=r["created_at"],
            )

    def get_recent_bets(self, user_id: int, limit: int = 5) -> List[BetRecord]:
        """Fetches the latest active and settled bets for the user (ignoring CLEARED)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM bets WHERE user_id = ? AND outcome != 'CLEARED'
                ORDER BY id DESC LIMIT ?
            """, (user_id, limit))
            rows = cursor.fetchall()

            return [
                BetRecord(
                    id=r["id"],
                    day_number=r["day_number"],
                    event_name=r["event_name"],
                    market=r["market"],
                    selection=r["selection"],
                    odds=r["odds"],
                    stake=r["stake"],
                    potential_return=r["potential_return"],
                    outcome=r["outcome"],
                    profit_loss=r["profit_loss"],
                    booking_code=r["booking_code"] if "booking_code" in r.keys() else None,
                    booking_url=r["booking_url"] if "booking_url" in r.keys() else None,
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_pending_bets(self, user_id: Optional[int] = None) -> List[Tuple[int, BetRecord]]:
        """Retrieves all placed/pending bets awaiting settlement as (user_id, BetRecord) tuples."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("""
                    SELECT * FROM bets WHERE user_id = ? AND outcome IN ('PLACED', 'PENDING')
                    ORDER BY id ASC
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT * FROM bets WHERE outcome IN ('PLACED', 'PENDING')
                    ORDER BY id ASC
                """)
            rows = cursor.fetchall()

            return [
                (
                    r["user_id"],
                    BetRecord(
                        id=r["id"],
                        day_number=r["day_number"],
                        event_name=r["event_name"],
                        market=r["market"],
                        selection=r["selection"],
                        odds=r["odds"],
                        stake=r["stake"],
                        potential_return=r["potential_return"],
                        outcome=r["outcome"],
                        profit_loss=r["profit_loss"],
                        booking_code=r["booking_code"] if "booking_code" in r.keys() else None,
                        booking_url=r["booking_url"] if "booking_url" in r.keys() else None,
                        created_at=r["created_at"],
                    )
                )
                for r in rows
            ]

    def get_proposed_bet(self, user_id: int) -> Optional[BetRecord]:
        """Fetches the latest active PROPOSED bet for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM bets WHERE user_id = ? AND outcome = 'PROPOSED'
                ORDER BY id DESC LIMIT 1
            """, (user_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return BetRecord(
                id=r["id"],
                day_number=r["day_number"],
                event_name=r["event_name"],
                market=r["market"],
                selection=r["selection"],
                odds=r["odds"],
                stake=r["stake"],
                potential_return=r["potential_return"],
                outcome=r["outcome"],
                profit_loss=r["profit_loss"],
                booking_code=r["booking_code"] if "booking_code" in r.keys() else None,
                booking_url=r["booking_url"] if "booking_url" in r.keys() else None,
                created_at=r["created_at"],
            )

    def get_user_sport_preference(self, user_id: int) -> str:
        """Retrieves user's preferred betting sport (default: basketball)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT preferred_sport FROM user_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["preferred_sport"]:
                return str(row["preferred_sport"]).lower()
            return "basketball"

    def set_user_sport_preference(self, user_id: int, sport: str):
        """Saves user's preferred betting sport."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_profiles SET preferred_sport = ?, updated_at = ? WHERE user_id = ?",
                (sport.lower(), get_current_time_iso(), user_id)
            )
            conn.commit()

    def get_user_performance_stats(self, user_id: int) -> Dict[str, Any]:
        """Calculates win rate %, total profit, ROI, and streak statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT current_day, current_balance, initial_stake, total_withdrawn,
                       total_won_bets, total_lost_bets, current_streak, highest_streak,
                       preferred_sport
                FROM user_profiles WHERE user_id = ?
            """, (user_id,))
            user_row = cursor.fetchone()
            if not user_row:
                return {}

            total_won = user_row["total_won_bets"] or 0
            total_lost = user_row["total_lost_bets"] or 0
            total_settled = total_won + total_lost
            win_rate = (total_won / total_settled * 100) if total_settled > 0 else 0.0

            cursor.execute("""
                SELECT COUNT(*) as total_bets,
                       COALESCE(SUM(profit_loss), 0.0) as net_profit,
                       COALESCE(AVG(odds), 0.0) as avg_odds
                FROM bets WHERE user_id = ? AND outcome IN ('WON', 'LOST')
            """, (user_id,))
            bet_row = cursor.fetchone()

            net_profit = bet_row["net_profit"] if bet_row else 0.0
            initial = user_row["initial_stake"] or 500.0
            roi = (net_profit / initial * 100) if initial > 0 else 0.0

            return {
                "current_day": user_row["current_day"],
                "current_balance": user_row["current_balance"],
                "initial_stake": initial,
                "total_withdrawn": user_row["total_withdrawn"],
                "total_won": total_won,
                "total_lost": total_lost,
                "total_settled": total_settled,
                "win_rate": round(win_rate, 1),
                "current_streak": user_row["current_streak"],
                "highest_streak": user_row["highest_streak"],
                "net_profit": round(net_profit, 2),
                "roi": round(roi, 1),
                "avg_odds": round(bet_row["avg_odds"], 2) if (bet_row and bet_row["avg_odds"]) else 1.55,
                "preferred_sport": user_row["preferred_sport"] or "basketball",
            }

    def reset_challenge(self, user_id: int, initial_stake: Optional[float] = None):
        """Resets the challenge to Day 1."""
        if initial_stake is None:
            initial_stake = config.DEFAULT_INITIAL_STAKE
        now = get_current_time_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profiles
                SET current_day = 1,
                    current_balance = ?,
                    initial_stake = ?,
                    total_withdrawn = 0.0,
                    total_won_bets = 0,
                    total_lost_bets = 0,
                    current_streak = 0,
                    status = 'ACTIVE',
                    updated_at = ?
                WHERE user_id = ?
            """, (initial_stake, initial_stake, now, user_id))
            conn.commit()

    def clear_all_user_memories(self, user_id: int, initial_stake: Optional[float] = None):
        """Wipes all previous bets, withdrawals, and resets ledger state to Day 1 with clean history."""
        if initial_stake is None:
            initial_stake = config.DEFAULT_INITIAL_STAKE
        now = get_current_time_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bets WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM withdrawals WHERE user_id = ?", (user_id,))
            cursor.execute("""
                UPDATE user_profiles
                SET current_day = 1,
                    current_balance = ?,
                    initial_stake = ?,
                    total_withdrawn = 0.0,
                    total_won_bets = 0,
                    total_lost_bets = 0,
                    current_streak = 0,
                    highest_streak = 0,
                    preferred_sport = 'basketball',
                    status = 'ACTIVE',
                    updated_at = ?
                WHERE user_id = ?
            """, (initial_stake, initial_stake, now, user_id))
            conn.commit()
            return True



# Alias for backwards/cross-module compatibility
SQLiteLedger = LedgerDB

