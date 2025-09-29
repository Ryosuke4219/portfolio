"""予算制御ロジック。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import BudgetBook, BudgetRule


@dataclass
class BudgetState:
    """予算消化の状態。"""

    spent_today_usd: float = 0.0


class BudgetManager:
    """予算ルールを評価・更新する。"""

    def __init__(self, book: BudgetBook) -> None:
        self.book = book
        self._states: dict[str, BudgetState] = {}
        self._today = date.today()

    def _rule_for(self, provider_name: str) -> BudgetRule:
        return self.book.overrides.get(provider_name, self.book.default)

    def run_budget(self, provider_name: str) -> float:
        """ラン単位の予算を取得する。"""

        return self._rule_for(provider_name).run_budget_usd

    def daily_budget(self, provider_name: str) -> float:
        """日次予算の上限を返す。"""

        return self._rule_for(provider_name).daily_budget_usd

    def stop_on_budget_exceed(self, provider_name: str) -> bool:
        """予算超過時に停止すべきかを返す。"""

        return self._rule_for(provider_name).stop_on_budget_exceed

    def should_stop_run(self, provider_name: str, cost_usd: float) -> bool:
        """ラン単位のコストが上限を超えた際に停止すべきかを判定する。"""

        rule = self._rule_for(provider_name)
        if rule.run_budget_usd <= 0:
            return False
        if not rule.stop_on_budget_exceed:
            return False
        return cost_usd > rule.run_budget_usd

    def notify_cost(self, provider_name: str, cost_usd: float) -> bool:
        """コスト消化を記録し、継続可否を返す。"""

        rule = self._rule_for(provider_name)
        today = date.today()
        if today != self._today:
            self._states.clear()
            self._today = today
        state = self._states.setdefault(provider_name, BudgetState())
        state.spent_today_usd += cost_usd
        if not rule.stop_on_budget_exceed:
            return True
        return state.spent_today_usd <= rule.daily_budget_usd

    def spent_today(self, provider_name: str) -> float:
        """本日消費した金額を返す。"""

        state = self._states.get(provider_name)
        return 0.0 if state is None else state.spent_today_usd
