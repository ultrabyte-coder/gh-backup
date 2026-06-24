"""Защита от превышения rate limit GitHub API перед запуском бэкапа."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.github_api import GitHubAPI

# Безопасные пороги (в запросах)
SAFE_MIN_REMAINING = 1000
WARN_MIN_REMAINING = 500
CRITICAL_MIN_REMAINING = 200


@dataclass
class RateLimitStatus:
    """Результат проверки лимитов."""

    allowed: bool
    remaining: int
    limit: int
    reset_datetime: datetime.datetime
    message: str
    severity: str  # "ok" | "warn" | "critical" | "blocked"

    @property
    def usage_percent(self) -> float:
        """Процент использованных запросов."""
        if self.limit == 0:
            return 100.0
        return ((self.limit - self.remaining) / self.limit) * 100


class RateLimitGuard:
    """
    Проверяет rate limit перед каждым запуском бэкапа.
    Блокирует запуск если лимит критически низкий.
    """

    def __init__(
        self,
        api: GitHubAPI,
        safe_threshold: int = SAFE_MIN_REMAINING,
        warn_threshold: int = WARN_MIN_REMAINING,
        critical_threshold: int = CRITICAL_MIN_REMAINING,
    ) -> None:
        self._api = api
        self._safe = safe_threshold
        self._warn = warn_threshold
        self._critical = critical_threshold

    async def check(self) -> RateLimitStatus:
        """Проверка текущего состояния rate limit."""
        try:
            rate = await self._api.get_rate_limit()
        except Exception as e:
            return RateLimitStatus(
                allowed=False,
                remaining=0,
                limit=0,
                reset_datetime=datetime.datetime.now(),
                message=f"Не удалось проверить rate limit: {e}",
                severity="blocked",
            )

        reset_dt = datetime.datetime.fromtimestamp(rate.reset_timestamp)
        remaining = rate.remaining

        if remaining >= self._safe:
            return RateLimitStatus(
                allowed=True,
                remaining=remaining,
                limit=rate.limit,
                reset_datetime=reset_dt,
                message=f"ОК — осталось {remaining}/{rate.limit} запросов",
                severity="ok",
            )

        if remaining >= self._warn:
            return RateLimitStatus(
                allowed=True,
                remaining=remaining,
                limit=rate.limit,
                reset_datetime=reset_dt,
                message=(
                    f"⚠️ Осталось {remaining}/{rate.limit} запросов. "
                    f"Бэкап разрешён, но рекомендуется подождать."
                ),
                severity="warn",
            )

        if remaining >= self._critical:
            minutes_until_reset = max(0, (reset_dt - datetime.datetime.now()).total_seconds() / 60)
            return RateLimitStatus(
                allowed=False,
                remaining=remaining,
                limit=rate.limit,
                reset_datetime=reset_dt,
                message=(
                    f"⛔ Мало запросов: {remaining}/{rate.limit}. "
                    f"Сброс через ~{minutes_until_reset:.0f} мин. "
                    f"Дождитесь обнуления счётчика."
                ),
                severity="critical",
            )

        minutes_until_reset = max(0, (reset_dt - datetime.datetime.now()).total_seconds() / 60)
        return RateLimitStatus(
            allowed=False,
            remaining=remaining,
            limit=rate.limit,
            reset_datetime=reset_dt,
            message=(
                f"🚫 БЛОКИРОВКА: осталось {remaining}/{rate.limit} запросов! "
                f"Сброс через ~{minutes_until_reset:.0f} мин. "
                f"Запуск бэкапа запрещён для защиты аккаунта."
            ),
            severity="blocked",
        )
