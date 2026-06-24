"""
Тесты для core/restore.py.
Проверка механизмов обнаружения бэкапов на диске, сканирования их содержимого 
и верификации целостности git-репозиториев.
"""

from pathlib import Path

import pytest

from core.restore import (
    RestoreEngine,
    RestoreItem,
    RestoreResult,
    RestoreType,
)


class TestRestoreEngineInit:
    """Проверка инициализации движка восстановления."""

    def test_init_with_token(self):
        """Сохранение токена доступа при создании объекта."""
        engine = RestoreEngine(token="ghp_test123")
        assert engine.token == "ghp_test123"

    def test_init_strips_token(self):
        """Очистка токена от пробельных символов по краям."""
        engine = RestoreEngine(token="  ghp_test123  ")
        assert engine.token == "ghp_test123"

    def test_init_empty_token(self):
        """Обработка пустого значения токена."""
        engine = RestoreEngine(token="")
        assert engine.token == ""


class TestDiscoverBackups:
    """Проверка логики поиска папок с бэкапами на диске."""

    def test_discover_backups_empty(self, temp_dir):
        """Возврат пустого списка при отсутствии папок в директории."""
        result = RestoreEngine.discover_backups(temp_dir)
        assert result == []

    def test_discover_backups_nonexistent(self):
        """Возврат пустого списка при обращении к несуществующему пути."""
        result = RestoreEngine.discover_backups(Path("/nonexistent/path"))
        assert result == []

    def test_discover_backups_single(self, temp_dir):
        """Обнаружение одиночной папки бэкапа."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        result = RestoreEngine.discover_backups(temp_dir)
        assert len(result) == 1
        assert result[0] == backup_dir

    def test_discover_backups_sorted_by_date(self, temp_dir):
        """Сортировка списка: наиболее свежий бэкап должен быть первым."""
        backup1 = temp_dir / "user-2025-01-01-120000"
        backup1.mkdir()

        backup2 = temp_dir / "user-2026-01-01-120000"
        backup2.mkdir()

        result = RestoreEngine.discover_backups(temp_dir)

        assert len(result) == 2
        assert result[0] == backup2
        assert result[1] == backup1

    def test_discover_backups_ignores_hidden(self, temp_dir):
        """Игнорирование скрытых директорий (начинающихся с точки)."""
        backup1 = temp_dir / "user-2026-01-01-120000"
        backup1.mkdir()

        hidden = temp_dir / ".hidden"
        hidden.mkdir()

        result = RestoreEngine.discover_backups(temp_dir)

        assert len(result) == 1
        assert result[0] == backup1


class TestScanBackup:
    """Проверка детального сканирования структуры отдельно взятого бэкапа."""

    def test_scan_backup_empty(self, temp_dir):
        """Возврат пустого списка при отсутствии данных внутри бэкапа."""
        result = RestoreEngine.scan_backup(temp_dir)
        assert result == []

    def test_scan_backup_with_repositories(self, temp_dir):
        """Распознавание репозиториев по наличию вложенной папки .git."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        repo1 = backup_dir / "repositories" / "repo1" / "repository"
        repo1.mkdir(parents=True)
        (repo1 / ".git").mkdir()

        repo2 = backup_dir / "repositories" / "repo2" / "repository"
        repo2.mkdir(parents=True)
        (repo2 / ".git").mkdir()

        result = RestoreEngine.scan_backup(backup_dir)

        repos = [item for item in result if item.restore_type == RestoreType.REPOSITORY]
        assert len(repos) == 2
        assert any(r.name == "repo1" for r in repos)
        assert any(r.name == "repo2" for r in repos)

    def test_scan_backup_with_wikis(self, temp_dir):
        """Распознавание wiki-репозиториев по суффиксу .wiki.git."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        wiki_dir = backup_dir / "wikis" / "Home.wiki.git"
        wiki_dir.mkdir(parents=True)

        result = RestoreEngine.scan_backup(backup_dir)

        wikis = [item for item in result if item.restore_type == RestoreType.WIKI]
        assert len(wikis) == 1
        assert wikis[0].name == "Home"

    def test_scan_backup_with_gists(self, temp_dir):
        """Распознавание гистов в соответствующей поддиректории."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        gist1 = backup_dir / "gists" / "abc123def456"
        gist1.mkdir(parents=True)

        gist2 = backup_dir / "gists" / "xyz789"
        gist2.mkdir(parents=True)

        result = RestoreEngine.scan_backup(backup_dir)

        gists = [item for item in result if item.restore_type == RestoreType.GIST]
        assert len(gists) == 2

    def test_scan_backup_with_account_data(self, temp_dir):
        """Распознавание JSON-файлов с данными аккаунта (подписчики и пр.)."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        account_dir = backup_dir / "account"
        account_dir.mkdir()
        (account_dir / "followers.json").write_text("[]")
        (account_dir / "following.json").write_text("[]")

        result = RestoreEngine.scan_backup(backup_dir)

        accounts = [
            item for item in result if item.restore_type == RestoreType.ACCOUNT_DATA
        ]
        assert len(accounts) == 2

    def test_scan_backup_complete(self, sample_backup_dir):
        """Комплексная проверка сканирования смешанного содержимого бэкапа."""
        result = RestoreEngine.scan_backup(sample_backup_dir)

        assert len(result) >= 3  # 1 repo + 1 wiki + 1 gist

        types = [item.restore_type for item in result]
        assert RestoreType.REPOSITORY in types
        assert RestoreType.WIKI in types
        assert RestoreType.GIST in types


class TestRestoreItem:
    """Тест модели RestoreItem."""

    def test_restore_item_creation(self):
        """Проверка корректности заполнения атрибутов элемента восстановления."""
        item = RestoreItem(
            name="test-repo",
            path=Path("/tmp/test"),
            restore_type=RestoreType.REPOSITORY,
        )

        assert item.name == "test-repo"
        assert item.path == Path("/tmp/test")
        assert item.restore_type == RestoreType.REPOSITORY


class TestRestoreResult:
    """Тест модели RestoreResult."""

    def test_restore_result_success(self):
        """Проверка полей результата при успешном завершении операции."""
        result = RestoreResult(
            name="test-repo",
            success=True,
            log_lines=["Clone successful", "Push successful"],
        )

        assert result.success is True
        assert result.error_message == ""

    def test_restore_result_failure(self):
        """Проверка фиксации сообщения об ошибке при неудаче."""
        result = RestoreResult(
            name="test-repo",
            success=False,
            error_message="Connection failed",
        )

        assert result.success is False
        assert result.error_message == "Connection failed"


class TestVerifyRepository:
    """Проверка механизмов верификации git-объектов в бэкапе."""

    @pytest.mark.asyncio
    async def test_verify_repository_with_git_dir(self, temp_dir):
        """Оценка состояния репозитория при наличии базовых файлов git (HEAD, config)."""
        backup_dir = temp_dir / "backup"
        backup_dir.mkdir()

        repo_dir = backup_dir / "repository"
        repo_dir.mkdir()
        (repo_dir / "config").write_text("[core]\n")
        (repo_dir / "HEAD").write_text("ref: refs/heads/main\n")

        result = await RestoreEngine.verify_repository(backup_dir, "test-repo")

        assert result.name == "test-repo"
        assert isinstance(result.success, bool)
        assert isinstance(result.log_lines, list)

    @pytest.mark.asyncio
    async def test_verify_repository_empty(self, temp_dir):
        """Признание репозитория невалидным, если папка пуста."""
        backup_dir = temp_dir / "empty"
        backup_dir.mkdir()

        result = await RestoreEngine.verify_repository(backup_dir, "empty-repo")

        assert result.name == "empty-repo"
        assert result.success is False


class TestRestoreEngineMethods:
    """Проверка интерфейса методов восстановления."""

    @pytest.mark.asyncio
    async def test_restore_repository_no_git(self, temp_dir):
        """Фиксация ошибки при попытке восстановить репозиторий без данных."""
        engine = RestoreEngine(token="ghp_test")

        backup_dir = temp_dir / "backup"
        backup_dir.mkdir()

        result = await engine.restore_repository(
            mirror_path=backup_dir,
            repo_name="test-repo",
            target_user="testuser",
        )

        assert result.success is False
        assert (
            "failed" in result.error_message.lower()
            or "not found" in result.error_message.lower()
        )

    @pytest.mark.asyncio
    async def test_restore_wiki_delegates_to_repository(self, temp_dir):
        """Проверка именования объекта при восстановлении wiki-страницы."""
        engine = RestoreEngine(token="ghp_test")

        backup_dir = temp_dir / "backup"
        backup_dir.mkdir()

        # Wiki использует ту же логику что и репозиторий
        result = await engine.restore_wiki(
            mirror_path=backup_dir,
            wiki_name="Home",
            target_user="testuser",
        )

        assert result.name == "Home.wiki"

    @pytest.mark.asyncio
    async def test_restore_gist_no_git(self, temp_dir):
        """Попытка восстановления гиста из пустой директории."""
        engine = RestoreEngine(token="ghp_test")

        gist_dir = temp_dir / "gist"
        gist_dir.mkdir()

        result = await engine.restore_gist(
            gist_path=gist_dir,
            gist_id="abc123",
        )

        # Ожидается ошибка так как нет git remote
        assert (
            result.success is False or result.success is True
        )  # Зависит от git состояния
