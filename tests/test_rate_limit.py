"""Тесты для core/rate_limit.py."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.rate_limit import RateLimitGuard, RateLimitStatus


@pytest.fixture
def mock_api():
    """Мок GitHubAPI."""
    api = MagicMock()
    api.get_rate_limit = AsyncMock()
    return api


class TestRateLimitStatus:
    """Тесты модели RateLimitStatus."""

    def test_usage_percent_normal(self):
        """Расчёт процента использованных запросов."""
        status = RateLimitStatus(
            allowed=True,
            remaining=2500,
            limit=5000,
            reset_datetime=datetime.datetime.now(),
            message="",
            severity="ok",
        )
        assert status.usage_percent == 50.0

    def test_usage_percent_zero_limit(self):
        """Деление на ноль — должен вернуть 100%."""
        status = RateLimitStatus(
            allowed=False,
            remaining=0,
            limit=0,
            reset_datetime=datetime.datetime.now(),
            message="",
            severity="blocked",
        )
        assert status.usage_percent == 100.0


class TestRateLimitGuardCheck:
    """Тесты проверки rate limit."""

    @pytest.mark.asyncio
    async def test_check_ok(self, mock_api):
        """ОК когда осталось много запросов."""
        mock_api.get_rate_limit.return_value = MagicMock(
            limit=5000, remaining=4500, reset_timestamp=int(datetime.datetime.now().timestamp()) + 3600
        )
        guard = RateLimitGuard(mock_api)
        status = await guard.check()

        assert status.allowed is True
        assert status.severity == "ok"
        assert status.remaining == 4500

    @pytest.mark.asyncio
    async def test_check_warn(self, mock_api):
        """Предупреждение при среднем уровне."""
        mock_api.get_rate_limit.return_value = MagicMock(
            limit=5000, remaining=800, reset_timestamp=int(datetime.datetime.now().timestamp()) + 1800
        )
        guard = RateLimitGuard(mock_api)
        status = await guard.check()

        assert status.allowed is True
        assert status.severity == "warn"
        assert status.remaining == 800

    @pytest.mark.asyncio
    async def test_check_critical(self, mock_api):
        """Блокировка при критическом уровне."""
        mock_api.get_rate_limit.return_value = MagicMock(
            limit=5000, remaining=300, reset_timestamp=int(datetime.datetime.now().timestamp()) + 900
        )
        guard = RateLimitGuard(mock_api)
        status = await guard.check()

        assert status.allowed is False
        assert status.severity == "critical"
        assert status.remaining == 300

    @pytest.mark.asyncio
    async def test_check_blocked(self, mock_api):
        """Полная блокировка при исчерпании."""
        mock_api.get_rate_limit.return_value = MagicMock(
            limit=5000, remaining=50, reset_timestamp=int(datetime.datetime.now().timestamp()) + 600
        )
        guard = RateLimitGuard(mock_api)
        status = await guard.check()

        assert status.allowed is False
        assert status.severity == "blocked"
        assert status.remaining == 50

    @pytest.mark.asyncio
    async def test_check_api_error(self, mock_api):
        """Обработка ошибки API."""
        mock_api.get_rate_limit.side_effect = Exception("Connection refused")
        guard = RateLimitGuard(mock_api)
        status = await guard.check()

        assert status.allowed is False
        assert status.severity == "blocked"
        assert "Не удалось проверить" in status.message

    @pytest.mark.asyncio
    async def test_check_custom_thresholds(self, mock_api):
        """Пороги настраиваются через параметры."""
        mock_api.get_rate_limit.return_value = MagicMock(
            limit=5000, remaining=1500, reset_timestamp=int(datetime.datetime.now().timestamp()) + 1200
        )
        guard = RateLimitGuard(
            mock_api,
            safe_threshold=1000,
            warn_threshold=500,
            critical_threshold=200,
        )
        status = await guard.check()

        assert status.allowed is True
        assert status.severity == "ok"
