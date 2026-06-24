"""
Тесты для core/config.py.
Проверка валидации данных пользователя, работы с файлом .env и маскировки секретов.
"""

import pytest

from core.config import Config


class TestConfigValidation:
    """Проверка логики валидации полей конфигурации."""

    def test_valid_config(self):
        """Успешное создание объекта при корректном заполнении всех полей."""
        config = Config(
            gh_username="testuser",
            gh_token="ghp_1234567890123456789012345678901234",
        )
        assert config.gh_username == "testuser"
        assert config.gh_token.startswith("ghp_")

    def test_username_too_long(self):
        """Отказ в создании, если длина username превышает предел GitHub (39 символов)."""
        with pytest.raises(ValueError):
            Config(
                gh_username="a" * 40,
                gh_token="ghp_1234567890123456789012345678901234",
            )

    def test_username_with_invalid_chars(self):
        """Запрет спецсимволов в имени пользователя (разрешены только латиница, цифры и дефис)."""
        with pytest.raises(ValueError, match="Неверный формат username"):
            Config(
                gh_username="test@user",
                gh_token="ghp_1234567890123456789012345678901234",
            )

    def test_username_starting_with_hyphen(self):
        """Запрет на использование дефиса в начале имени пользователя."""
        with pytest.raises(ValueError, match="Неверный формат username"):
            Config(
                gh_username="-testuser",
                gh_token="ghp_1234567890123456789012345678901234",
            )

    def test_username_ending_with_hyphen(self):
        """Запрет на использование дефиса в конце имени пользователя."""
        with pytest.raises(ValueError, match="Неверный формат username"):
            Config(
                gh_username="testuser-",
                gh_token="ghp_1234567890123456789012345678901234",
            )

    def test_valid_username_with_hyphens(self):
        """Поддержка дефисов внутри имени пользователя (стандартный формат GitHub)."""
        config = Config(
            gh_username="test-user-name",
            gh_token="ghp_1234567890123456789012345678901234",
        )
        assert config.gh_username == "test-user-name"

    def test_token_too_short(self):
        """Минимальный порог длины токена для предотвращения ввода мусора."""
        with pytest.raises(ValueError):
            Config(
                gh_username="testuser",
                gh_token="ghp_12345",
            )

    def test_invalid_token_format(self):
        """Проверка наличия обязательных префиксов (ghp_, github_pat_ и др.)."""
        with pytest.raises(ValueError, match="Неверный формат токена"):
            Config(
                gh_username="testuser",
                gh_token="invalid_token_here",
            )

    def test_valid_github_pat_token(self):
        """Поддержка формата GitHub Personal Access Token (fine-grained)."""
        config = Config(
            gh_username="testuser",
            gh_token="github_pat_123456789012345678901234567890",
        )
        assert config.gh_token.startswith("github_pat_")

    def test_empty_token(self):
        """Обработка пустого значения или строки из пробелов."""
        with pytest.raises(ValueError):
            Config(
                gh_username="testuser",
                gh_token="   ",
            )


class TestConfigPersistence:
    """Проверка механизмов сохранения и восстановления настроек из файла."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_save_and_load_env_file(self, temp_dir):
        """Цикл записи в .env и последующего чтения: данные должны совпадать."""
        config = Config(
            gh_username="testuser",
            gh_token=self.VALID_TOKEN,
            backup_dir="my_backups",
        )

        env_file = config.save_to_env_file(temp_dir)
        assert env_file.exists()

        # Проверка прав доступа: файл должен быть доступен только владельцу (0o600)
        import stat

        file_stat = env_file.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        assert file_mode == 0o600

        loaded = Config.from_env_file(temp_dir)
        assert loaded is not None
        assert loaded.gh_username == "testuser"
        assert loaded.gh_token == self.VALID_TOKEN
        assert loaded.backup_dir == "my_backups"

    def test_load_env_file_missing(self, temp_dir):
        """Корректная обработка отсутствия файла настроек."""
        result = Config.from_env_file(temp_dir)
        assert result is None

    def test_remove_env_file(self, temp_dir):
        """Удаление файла конфигурации из файловой системы."""
        config = Config(
            gh_username="testuser",
            gh_token=self.VALID_TOKEN,
        )
        env_file = config.save_to_env_file(temp_dir)
        assert env_file.exists()

        result = Config.remove_env_file(temp_dir)
        assert result is True
        assert not env_file.exists()

        # Повторное удаление не должно вызывать исключение
        result = Config.remove_env_file(temp_dir)
        assert result is False

    def test_env_file_with_quotes(self, temp_dir):
        """Очистка значений от кавычек (одинарных и двойных) при загрузке .env."""
        env_file = temp_dir / ".env"
        env_file.write_text(
            "GH_USERNAME='testuser'\n"
            "GH_TOKEN='ghp_1234567890123456789012345678901234'\n"
            'BACKUP_DIR="my_backups"\n'
        )

        config = Config.from_env_file(temp_dir)
        assert config is not None
        assert config.gh_username == "testuser"
        assert config.backup_dir == "my_backups"

    def test_env_file_without_required_fields(self, temp_dir):
        """Игнорирование .env файла, в котором отсутствуют критически важные поля."""
        env_file = temp_dir / ".env"
        env_file.write_text("GH_USERNAME='testuser'\n")

        result = Config.from_env_file(temp_dir)
        assert result is None


class TestMaskedToken:
    """Проверка безопасности отображения токена."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_masked_token_normal(self):
        """Скрытие центральной части токена при выводе в лог или UI."""
        config = Config(
            gh_username="testuser",
            gh_token=self.VALID_TOKEN,
        )
        masked = config.masked_token()
        assert masked.startswith("ghp_")
        assert masked.endswith("1234")
        assert "..." in masked

    def test_masked_token_short(self):
        """Маскировка минимально допустимого по длине токена."""
        config = Config(
            gh_username="testuser",
            gh_token="ghp_1234567890123456789012345678901234",
        )
        masked = config.masked_token()
        assert len(masked) < len(config.gh_token)
        assert "..." in masked
