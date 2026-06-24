"""
Тесты для core/github_api.py.
Проверка взаимодействия с API GitHub: аутентификация, поиск пользователей и контроль лимитов запросов.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.github_api import (
    GitHubAPI,
    GitHubUser,
    InvalidTokenError,
    RateLimit,
    UserNotFoundError,
)


@pytest.fixture
def mock_httpx_client():
    """Подмена httpx AsyncClient для изоляции сетевых запросов."""
    with patch("core.github_api.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock()
        mock_client.aclose = AsyncMock()
        mock_client_class.return_value = mock_client
        yield mock_client


class TestGitHubAPIInit:
    """Проверка инициализации экземпляра GitHubAPI."""

    def test_init_with_token(self):
        """Сохранение переданного токена."""
        api = GitHubAPI(token="ghp_test123")
        assert api.token == "ghp_test123"

    def test_init_strips_token(self):
        """Очистка токена от лишних пробелов по краям."""
        api = GitHubAPI(token="  ghp_test123  ")
        assert api.token == "ghp_test123"

    def test_init_empty_token(self):
        """Обработка пустого токена при создании объекта."""
        api = GitHubAPI(token="")
        assert api.token == ""


class TestCheckToken:
    """Тесты проверки валидности токена через запрос к /user."""

    @pytest.mark.asyncio
    async def test_check_token_valid(self, mock_httpx_client):
        """Успешное преобразование ответа API в объект GitHubUser при валидном токене."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "public_repos": 10,
            "type": "User",
        }
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="ghp_valid_token")
        user = await api.check_token()

        assert isinstance(user, GitHubUser)
        assert user.login == "testuser"
        assert user.name == "Test User"
        assert user.public_repos == 10
        assert user.type == "User"

    @pytest.mark.asyncio
    async def test_check_token_404(self, mock_httpx_client):
        """Проброс ошибки через raise_for_status при получении 404 кода."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(side_effect=Exception("404"))
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="ghp_1234567890123456789012345678901234")

        with pytest.raises(Exception, match="404"):
            await api.check_token()


class TestCheckUser:
    """Проверка существования целевого пользователя на GitHub."""

    @pytest.mark.asyncio
    async def test_check_user_exists(self, mock_httpx_client):
        """Возврат данных профиля при успешном нахождении пользователя."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "login": "octocat",
            "name": "The Octocat",
            "public_repos": 100,
            "type": "User",
        }
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="ghp_test")
        user = await api.check_user("octocat")

        assert user.login == "octocat"
        assert user.name == "The Octocat"
        assert user.public_repos == 100

    @pytest.mark.asyncio
    async def test_check_user_not_found(self, mock_httpx_client):
        """Возбуждение UserNotFoundError при отсутствии профиля (код 404)."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="ghp_test")

        with pytest.raises(UserNotFoundError) as exc_info:
            await api.check_user("nonexistent_user_xyz")

        assert exc_info.value.username == "nonexistent_user_xyz"


class TestGetRateLimit:
    """Запрос текущих лимитов API (Rate Limits)."""

    @pytest.mark.asyncio
    async def test_get_rate_limit(self, mock_httpx_client):
        """Извлечение данных о доступных запросах и времени сброса лимита."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": 4999,
                    "reset": 1234567890,
                }
            }
        }
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="ghp_test")
        rate = await api.get_rate_limit()

        assert isinstance(rate, RateLimit)
        assert rate.limit == 5000
        assert rate.remaining == 4999
        assert rate.reset_timestamp == 1234567890


class TestValidateAll:
    """Комплексная проверка всей цепочки валидации."""

    @pytest.mark.asyncio
    async def test_validate_all_success(self, mock_httpx_client):
        """Успешное выполнение всех этапов: проверка токена, пользователя и лимитов."""

        def mock_get(url):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            if url == "/user":
                mock_response.json.return_value = {
                    "login": "testuser",
                    "name": "Test",
                    "public_repos": 10,
                    "type": "User",
                }
            elif url == "/users/testuser":
                mock_response.json.return_value = {
                    "login": "testuser",
                    "name": "Test",
                    "public_repos": 10,
                    "type": "User",
                }
            elif url == "/rate_limit":
                mock_response.json.return_value = {
                    "resources": {
                        "core": {"limit": 5000, "remaining": 4999, "reset": 1234567890}
                    }
                }
            return mock_response

        mock_httpx_client.get.side_effect = lambda url: mock_get(url)

        api = GitHubAPI(token="ghp_valid")
        result = await api.validate_all("testuser")

        assert "token_user" in result
        assert "target_user" in result
        assert "rate_limit" in result
        assert result["token_user"].login == "testuser"
        assert result["target_user"].login == "testuser"
        assert result["token_matches_user"] is True

    @pytest.mark.asyncio
    async def test_validate_all_invalid_token(self, mock_httpx_client):
        """Остановка валидации при получении 401 кода (Invalid Token)."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_httpx_client.get.return_value = mock_response

        api = GitHubAPI(token="invalid")

        with pytest.raises(InvalidTokenError):
            await api.validate_all("testuser")

    @pytest.mark.asyncio
    async def test_validate_all_user_not_found(self, mock_httpx_client):
        """Остановка валидации, если целевой профиль не обнаружен."""

        def mock_get(url):
            mock_response = MagicMock()
            if url == "/user":
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "login": "tokenowner",
                    "name": "Owner",
                    "public_repos": 5,
                    "type": "User",
                }
            elif url == "/users/testuser":
                mock_response.status_code = 404
            return mock_response

        mock_httpx_client.get.side_effect = lambda url: mock_get(url)

        api = GitHubAPI(token="ghp_valid")

        with pytest.raises(UserNotFoundError):
            await api.validate_all("testuser")


class TestClose:
    """Завершение работы с API."""

    @pytest.mark.asyncio
    async def test_close(self, mock_httpx_client):
        """Вызов закрытия асинхронного клиента httpx."""
        api = GitHubAPI(token="ghp_test")
        await api.close()

        mock_httpx_client.aclose.assert_called_once()
