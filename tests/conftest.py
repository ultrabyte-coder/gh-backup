"""
Конфигурация pytest и общие фикстуры.
Подготовка временного окружения, тестовых данных и структуры папок для тестов.
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Создание временной директории на время выполнения теста."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_dict():
    """Словарь с эталонными настройками для проверки валидации."""
    return {
        "gh_username": "testuser",
        "gh_token": "ghp_1234567890123456789012345678901234",
        "backup_dir": "backups",
    }


@pytest.fixture
def sample_backup_dir(temp_dir):
    """
    Генерация структуры папок, имитирующей реальный бэкап.
    Внутри: репозиторий с .git, вики-страница и гист.
    """
    backup_dir = temp_dir / "testuser-2026-01-01-120000"
    backup_dir.mkdir()

    # Имитация репозитория: repositories/имя/repository/.git
    repos_dir = backup_dir / "repositories" / "test-repo"
    repos_dir.mkdir(parents=True)
    (repos_dir / "repository").mkdir()
    (repos_dir / "repository" / ".git").mkdir()

    # Имитация wiki: wikis/имя.wiki.git
    wikis_dir = backup_dir / "wikis"
    wikis_dir.mkdir()
    (wikis_dir / "test.wiki.git").mkdir()

    # Имитация гиста: gists/id
    gists_dir = backup_dir / "gists" / "abc123"
    gists_dir.mkdir(parents=True)

    return backup_dir


@pytest.fixture
def mock_env_file(temp_dir):
    """Запись корректного .env файла во временную папку."""
    env_file = temp_dir / ".env"
    env_file.write_text(
        "GH_USERNAME='testuser'\n"
        "GH_TOKEN='ghp_1234567890123456789012345678901234'\n"
        "BACKUP_DIR='backups'\n"
    )
    return env_file


@pytest.fixture
def invalid_token_env(temp_dir):
    """Запись .env файла с заведомо кривым токеном для проверки ошибок."""
    env_file = temp_dir / ".env"
    env_file.write_text("GH_USERNAME='testuser'\nGH_TOKEN='invalid_token'\n")
    return env_file
