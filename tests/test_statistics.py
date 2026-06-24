"""
Тесты для core/statistics.py.
Проверка точности подсчета git-репозиториев, расчета объемов данных 
и формирования сводных отчетов по архивам бэкапов.
"""

from pathlib import Path

from core.statistics import (
    BackupStats,
    collect_all_stats,
    collect_stats,
    count_git_dirs,
    human_size,
)


class TestCountGitDirs:
    """Проверка рекурсивного поиска и подсчета git-директорий."""

    def test_count_git_dirs_empty(self, temp_dir):
        """Возврат 0 при поиске в пустой директории."""
        result = count_git_dirs(temp_dir)
        assert result == 0

    def test_count_git_dirs_with_matches(self, temp_dir):
        """Подсчет нескольких независимых .git папок в корне структуры."""
        (temp_dir / "repo1" / ".git").mkdir(parents=True)
        (temp_dir / "repo2" / ".git").mkdir(parents=True)
        (temp_dir / "repo3" / ".git").mkdir(parents=True)

        result = count_git_dirs(temp_dir)
        assert result == 3

    def test_count_git_dirs_nested(self, temp_dir):
        """Корректный учет вложенных репозиториев на разных уровнях дерева."""
        (temp_dir / "level1" / "level2" / ".git").mkdir(parents=True)
        (temp_dir / "level1" / ".git").mkdir()

        result = count_git_dirs(temp_dir)
        assert result == 2

    def test_count_git_dirs_nonexistent(self):
        """Обработка попытки сканирования по несуществующему пути."""
        result = count_git_dirs(Path("/nonexistent/path"))
        assert result == 0


class TestHumanSize:
    """Проверка преобразования байтов в читаемый формат (B, KB, MB, GB)."""

    def test_human_size_nonexistent(self):
        """Возврат '0 B' для путей, которых нет в файловой системе."""
        result = human_size(Path("/nonexistent/path"))
        assert result == "0 B"

    def test_human_size_directory(self, temp_dir):
        """Расчет суммарного веса всех файлов внутри директории."""
        (temp_dir / "file1.txt").write_text("test" * 100)
        (temp_dir / "file2.txt").write_text("test" * 200)

        result = human_size(temp_dir)
        assert isinstance(result, str)
        assert any(unit in result for unit in ["B", "KB", "MB"])


class TestCollectStats:
    """Проверка формирования детальной статистики по конкретному бэкапу."""

    def test_collect_stats_empty(self, temp_dir):
        """Создание объекта статистики с нулевыми показателями для пустой папки."""
        # collect_stats возвращает BackupStats даже для пустой директории
        # Но с repos=0, wikis=0, gists=0
        result = collect_stats(temp_dir)
        # Проверка того, что статистика собрана, но с нулевыми значениями
        assert result is not None
        assert result.repos == 0
        assert result.wikis == 0

    def test_collect_stats_nonexistent(self):
        """Возврат None, если папка бэкапа не найдена."""
        result = collect_stats(Path("/nonexistent/path"))
        assert result is None

    def test_collect_stats_with_backup(self, sample_backup_dir):
        """Валидация данных для полноценного бэкапа (репо, wiki, гисты)."""
        result = collect_stats(sample_backup_dir)

        assert result is not None
        assert result.name == "testuser-2026-01-01-120000"
        assert result.repos == 1
        assert result.wikis == 1
        assert result.gists == 1
        assert result.total_size != "0 B"
        assert result.mode == "quick"  # нет метаданных issues/pulls

    def test_collect_stats_full_mode(self, temp_dir):
        """Автоматическое определение режима 'full' при наличии метаданных (issues/pulls)."""
        backup_dir = temp_dir / "testuser-2026-01-01-120000"
        backup_dir.mkdir()

        # Создаю репозиторий с метаданными
        repo_dir = backup_dir / "repositories" / "test-repo"
        repo_dir.mkdir(parents=True)
        (repo_dir / "repository").mkdir()
        (repo_dir / "repository" / ".git").mkdir()

        # Добавляю метаданные
        (repo_dir / "issues").mkdir()
        (repo_dir / "pulls").mkdir()

        result = collect_stats(backup_dir)
        assert result is not None
        assert result.mode == "full"

    def test_collect_stats_from_directory_name(self, temp_dir):
        """Парсинг временной метки из метаданных файла при создании статистики."""
        backup_dir = temp_dir / "myuser-2025-12-31-235959"
        backup_dir.mkdir()
        (backup_dir / "repositories").mkdir()
        (backup_dir / "repositories" / "test-repo").mkdir()
        (backup_dir / "repositories" / "test-repo" / "repository").mkdir()
        (backup_dir / "repositories" / "test-repo" / "repository" / ".git").mkdir()

        result = collect_stats(backup_dir)
        assert result is not None
        # Проверка того, что дата собрана (из mtime так как формат имени может не парситься)
        assert result.created_at is not None


class TestCollectAllStats:
    """Проверка массового сбора статистики по всем имеющимся бэкапам."""

    def test_collect_all_stats_empty(self, temp_dir):
        """Возврат пустого списка при отсутствии архивов."""
        result = collect_all_stats(temp_dir)
        assert result == []

    def test_collect_all_stats_nonexistent(self):
        """Обработка обращения к отсутствующей корневой директории бэкапов."""
        result = collect_all_stats(Path("/nonexistent/path"))
        assert result == []

    def test_collect_all_stats_multiple(self, temp_dir):
        """Проверка сортировки: свежие бэкапы должны быть в начале списка."""
        # Создаю два бэкапа
        backup1 = temp_dir / "user-2025-01-01-120000"
        backup1.mkdir()
        (backup1 / "repositories").mkdir()
        (backup1 / "repositories" / "repo1").mkdir()
        (backup1 / "repositories" / "repo1" / "repository").mkdir()
        (backup1 / "repositories" / "repo1" / "repository" / ".git").mkdir()

        import time

        time.sleep(0.1)  # Небольшая задержка чтобы mtime был разным

        backup2 = temp_dir / "user-2026-01-01-120000"
        backup2.mkdir()
        (backup2 / "repositories").mkdir()
        (backup2 / "repositories" / "repo1").mkdir()
        (backup2 / "repositories" / "repo1" / "repository").mkdir()
        (backup2 / "repositories" / "repo1" / "repository" / ".git").mkdir()

        result = collect_all_stats(temp_dir)

        assert len(result) == 2
        # Новые бэкапы (с большим mtime) первыми
        # backup2 создан позже, поэтому должен быть первым
        assert result[0].name == "user-2026-01-01-120000"
        assert result[1].name == "user-2025-01-01-120000"

    def test_collect_all_stats_ignores_hidden(self, temp_dir):
        """Исключение скрытых директорий из итогового отчета."""
        # Создаю обычный и скрытый бэкап
        backup1 = temp_dir / "user-2026-01-01-120000"
        backup1.mkdir()
        (backup1 / "repositories").mkdir()

        backup2 = temp_dir / ".hidden-backup"
        backup2.mkdir()
        (backup2 / "repositories").mkdir()

        result = collect_all_stats(temp_dir)

        assert len(result) == 1
        assert result[0].name == "user-2026-01-01-120000"


class TestBackupStats:
    """Проверка строкового представления (summary) объекта статистики."""

    def test_backup_stats_summary(self):
        """Валидация формата краткой сводки с использованием эмодзи."""
        stats = BackupStats(
            backup_dir=Path("/tmp/test"),
            name="testuser-2026-01-01-120000",
            created_at=None,  # type: ignore
            repos=5,
            wikis=2,
            gists=3,
            total_size="1.5 GB",
        )

        assert "📦 5 репо" in stats.summary
        assert "📖 2 wiki" in stats.summary
        assert "📝 3 gists" in stats.summary
        assert "💾 1.5 GB" in stats.summary
