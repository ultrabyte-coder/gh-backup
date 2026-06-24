"""
Взаимодействие с GitHub API. 
Проверка токенов, существования юзеров и остатков по лимитам запросов.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_BASE = "https://api.github.com"
TIMEOUT = 15.0


@dataclass(frozen=True)
class GitHubUser:
    """Данные профиля, которые вытягиваю для проверки."""
    login: str
    name: str | None
    public_repos: int
    type: str # User или Organization


@dataclass(frozen=True)
class RateLimit:
    """Статус лимитов API, чтобы не упереться в потолок при бэкапе."""
    limit: int
    remaining: int
    reset_timestamp: int  # unix epoch


class GitHubAPI:
    """
    Клиент для базовых проверок перед началом работы. 
    Использую асинхронный httpx, чтобы не блокировать поток.
    """

    def __init__(self, token: str) -> None:
        self.token = token.strip()
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "gh-backup/1.0",
            },
            timeout=TIMEOUT,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Запросы к API
    # ------------------------------------------------------------------

    async def check_user(self, username: str) -> GitHubUser:
        """Проверка существования целевого аккаунта."""
        resp = await self._client.get(f"/users/{username}")
        if resp.status_code == 404:
            raise UserNotFoundError(username)
        resp.raise_for_status()
        data = resp.json()
        return GitHubUser(
            login=data["login"],
            name=data.get("name"),
            public_repos=data.get("public_repos", 0),
            type=data.get("type", "User"),
        )

    async def check_token(self) -> GitHubUser:
        """Проверка прав доступа самого токена."""
        resp = await self._client.get("/user")
        if resp.status_code == 401:
            raise InvalidTokenError()
        resp.raise_for_status()
        data = resp.json()
        return GitHubUser(
            login=data["login"],
            name=data.get("name"),
            public_repos=data.get("public_repos", 0),
            type=data.get("type", "User"),
        )

    async def get_rate_limit(self) -> RateLimit:
        """Запрос текущего состояния Rate Limit для текущего токена."""
        resp = await self._client.get("/rate_limit")
        resp.raise_for_status()
        core = resp.json()["resources"]["core"]
        return RateLimit(
            limit=core["limit"],
            remaining=core["remaining"],
            reset_timestamp=core["reset"],
        )

    async def validate_all(self, username: str) -> dict:
        """
        Проверка всего и сразу перед запуском процесса: 
        токен, юзер и остаток лимита запросов.
        """
        token_user = await self.check_token()
        target_user = await self.check_user(username)
        rate = await self.get_rate_limit()

        return {
            "token_user": token_user,
            "target_user": target_user,
            "rate_limit": rate,
            "token_matches_user": token_user.login == username,
        }


# ------------------------------------------------------------------
# Ошибки API
# ------------------------------------------------------------------


class UserNotFoundError(Exception):
    """Такого логина на GitHub нет."""
    def __init__(self, username: str) -> None:
        super().__init__(f"Пользователь '{username}' не найден на GitHub")
        self.username = username


class InvalidTokenError(Exception):
    """Проблема с авторизацией (токен протух или неверный)."""
    def __init__(self) -> None:
        super().__init__("Токен невалиден или отозван")
