"""
Тесты для core/backup_runner.py.
Проверка логики запуска бэкапа, управления процессами, парсинга вывода и механизма блокировок.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.backup_runner import (
    GITHUB_BACKUP_BIN,
    BackupMode,
    BackupResult,
    BackupRunner,
    BackupStatus,
    LockError,
)


class TestBackupMode:
    """Проверка констант режимов бэкапа (FULL/QUICK)."""

    def test_backup_mode_full(self):
        """Соответствие FULL режима значению 'full'."""
        assert BackupMode.FULL.value == "full"

    def test_backup_mode_quick(self):
        """Соответствие QUICK режима значению 'quick'."""
        assert BackupMode.QUICK.value == "quick"


class TestBackupStatus:
    """Проверка возможных состояний процесса бэкапа."""

    def test_backup_status_values(self):
        """Проверка строковых значений для всех статусов (успех, ошибка, отмена)."""
        assert BackupStatus.SUCCESS.value == "success"
        assert BackupStatus.FAILED.value == "failed"
        assert BackupStatus.CANCELLED.value == "cancelled"


class TestBackupResult:
    """Тесты итоговой структуры результата выполнения."""

    def test_backup_result_success(self):
        """Валидация полей при успешном завершении задачи."""
        import datetime

        result = BackupResult(
            status=BackupStatus.SUCCESS,
            backup_dir=Path("/tmp/backup"),
            start_time=datetime.datetime.now(),
            duration_seconds=10.5,
        )

        assert result.status == BackupStatus.SUCCESS
        assert result.duration_seconds == 10.5
        assert result.error_message == ""

    def test_backup_result_failed(self):
        """Проверка сохранения сообщения об ошибке при сбое."""
        import datetime

        result = BackupResult(
            status=BackupStatus.FAILED,
            backup_dir=Path("/tmp/backup"),
            start_time=datetime.datetime.now(),
            error_message="Connection failed",
        )

        assert result.status == BackupStatus.FAILED
        assert result.error_message == "Connection failed"

    def test_backup_result_cancelled(self):
        """Проверка статуса при ручной отмене операции."""
        import datetime

        result = BackupResult(
            status=BackupStatus.CANCELLED,
            backup_dir=Path("/tmp/backup"),
            start_time=datetime.datetime.now(),
            error_message="Cancelled by user",
        )

        assert result.status == BackupStatus.CANCELLED


class TestLockError:
    """Тесты исключения блокировки."""

    def test_lock_error_message(self):
        """Проверка корректного проброса сообщения в Exception."""
        error = LockError("Бэкап уже запущен")
        assert str(error) == "Бэкап уже запущен"


class TestBackupRunnerInit:
    """Тесты конструктора и начального состояния BackupRunner."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_init_basic(self, temp_dir):
        """Проверка присвоения базовых атрибутов (username, token, path)."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        assert runner.username == "testuser"
        assert runner.token == self.VALID_TOKEN
        assert runner.backup_base == temp_dir
        assert runner.mode == BackupMode.FULL
        assert runner.incremental is False

    def test_init_with_mode(self, temp_dir):
        """Проверка установки расширенных параметров (режим, инкрементальность)."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
            mode=BackupMode.QUICK,
            incremental=True,
        )

        assert runner.mode == BackupMode.QUICK
        assert runner.incremental is True


class TestMakeBackupDir:
    """Тесты генерации путей для хранения копий."""

    def test_make_backup_dir_name_format(self, temp_dir):
        """Валидация формата имени папки по регулярному выражению."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
        )

        import re

        dir_path = runner._make_backup_dir()

        # Формат: username-YYYY-MM-DD-HHMMSS
        pattern = r"testuser-\d{4}-\d{2}-\d{2}-\d{6}"
        assert re.match(pattern, dir_path.name) is not None
        assert dir_path.parent == temp_dir


class TestFindLatestBackup:
    """Тесты поиска последнего существующего бэкапа для инкрементального режима."""

    def test_find_latest_backup_empty(self, temp_dir):
        """Возврат None при отсутствии бэкапов."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
        )
        assert runner._find_latest_backup() is None

    def test_find_latest_backup_nonexistent_base(self):
        """Возврат None при несуществующей базовой директории."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=Path("/nonexistent/path"),
        )
        assert runner._find_latest_backup() is None

    def test_find_latest_backup_returns_newest(self, temp_dir):
        """Возврат самого свежего бэкапа (по mtime)."""
        import time

        old = temp_dir / "testuser-2025-01-01-120000"
        old.mkdir()
        time.sleep(0.05)
        new = temp_dir / "testuser-2026-06-01-120000"
        new.mkdir()

        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
        )
        result = runner._find_latest_backup()
        assert result == new

    def test_find_latest_backup_ignores_other_users(self, temp_dir):
        """Игнорирование бэкапов других пользователей."""
        (temp_dir / "otheruser-2026-01-01-120000").mkdir()
        mine = temp_dir / "testuser-2026-01-01-120000"
        mine.mkdir()

        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
        )
        result = runner._find_latest_backup()
        assert result == mine


class TestGetBackupDir:
    """Тесты определения папки для бэкапа (инкрементально vs новая)."""

    def test_get_backup_dir_new_when_not_incremental(self, temp_dir):
        """Новая папка создаётся при обычном режиме."""
        (temp_dir / "testuser-2025-01-01-120000").mkdir()

        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            incremental=False,
        )
        result = runner._get_backup_dir()
        assert result != temp_dir / "testuser-2025-01-01-120000"
        assert result.name.startswith("testuser-")

    def test_get_backup_dir_existing_when_incremental(self, temp_dir):
        """Используется существующий бэкап при инкрементальном режиме."""
        existing = temp_dir / "testuser-2025-01-01-120000"
        existing.mkdir()

        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            incremental=True,
        )
        result = runner._get_backup_dir()
        assert result == existing

    def test_get_backup_dir_new_when_incremental_but_empty(self, temp_dir):
        """Новая папка при инкрементальном режиме, если бэкапов нет."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            incremental=True,
        )
        result = runner._get_backup_dir()
        assert result.name.startswith("testuser-")


class TestBuildCommand:
    """Тесты генерации аргументов командной строки для CLI-утилиты."""

    def test_build_command_full_mode(self, temp_dir):
        """Набор флагов для полной копии аккаунта."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            mode=BackupMode.FULL,
        )

        backup_dir = temp_dir / "backup"
        cmd = runner._build_command(backup_dir)

        assert GITHUB_BACKUP_BIN in cmd or "github-backup" in cmd[0]
        assert "testuser" in cmd
        assert "-t" in cmd
        assert "-o" in cmd
        assert "--all" in cmd
        assert "--private" in cmd
        assert "--fork" in cmd
        assert "--gists" in cmd
        assert "--starred-gists" in cmd
        assert "--starred" in cmd
        assert "--pull-details" in cmd
        assert "--assets" in cmd
        assert "--attachments" in cmd

    def test_build_command_quick_mode(self, temp_dir):
        """Набор флагов для быстрого бэкапа (только репозитории и вики)."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            mode=BackupMode.QUICK,
        )

        backup_dir = temp_dir / "backup"
        cmd = runner._build_command(backup_dir)

        assert "--private" in cmd
        assert "--repositories" in cmd
        assert "--wikis" in cmd
        assert "--all" not in cmd

    def test_build_command_incremental(self, temp_dir):
        """Добавление флага --incremental в команду."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
            incremental=True,
        )

        backup_dir = temp_dir / "backup"
        cmd = runner._build_command(backup_dir)

        assert "--incremental" in cmd

    def test_build_command_throttle(self, temp_dir):
        """Наличие флагов тротлинга для защиты от исчерпания rate limit."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=temp_dir,
        )

        backup_dir = temp_dir / "backup"
        cmd = runner._build_command(backup_dir)

        assert "--throttle-limit" in cmd
        assert "--throttle-pause" in cmd


class TestAcquireLock:
    """Тесты механизма предотвращения одновременных запусков."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_acquire_lock_success(self, temp_dir):
        """Создание лок-файла при отсутствии конкуренции."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        runner._acquire_lock()

        lock_file = temp_dir / ".backup.lock"
        assert lock_file.exists()

        # Очищаем
        runner._release_lock()

    def test_acquire_lock_stale(self, temp_dir):
        """Перехват блокировки, если процесс из старого лок-файла уже не существует."""
        lock_file = temp_dir / ".backup.lock"
        lock_file.write_text("99999")  # Заведомо несуществующий PID

        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        runner._acquire_lock()

        assert lock_file.exists()
        assert lock_file.read_text() != "99999"

        runner._release_lock()

    def test_acquire_lock_running(self, temp_dir):
        """Возбуждение исключения LockError при обнаружении активного процесса."""
        lock_file = temp_dir / ".backup.lock"
        lock_file.write_text(str(__import__("os").getpid()))

        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        with pytest.raises(LockError, match="Бэкап уже запущен"):
            runner._acquire_lock()

        lock_file.unlink()


class TestReleaseLock:
    """Тесты очистки блокировок."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_release_lock_removes_file(self, temp_dir):
        """Удаление файла .backup.lock при завершении работы."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        runner._acquire_lock()
        lock_file = temp_dir / ".backup.lock"
        assert lock_file.exists()

        runner._release_lock()
        assert not lock_file.exists()

    def test_release_lock_no_file(self, temp_dir):
        """Отсутствие ошибок при попытке освободить несуществующий замок."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=temp_dir,
        )

        runner._release_lock()


class TestParseLogLine:
    """Тесты анализа текстового вывода утилиты бэкапа."""

    VALID_TOKEN = "ghp_1234567890123456789012345678901234"

    def test_parse_log_line_stores_line(self):
        """Сохранение каждой строки вывода в лог."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=Path("/tmp"),
        )

        runner._parse_log_line("Some log line")

        assert len(runner._log_lines) == 1
        assert runner._log_lines[0] == "Some log line"

    def test_parse_log_line_cloning(self):
        """Запись строки с клонированием в лог (без инкремента счётчика)."""
        runner = BackupRunner(
            username="testuser",
            token=self.VALID_TOKEN,
            backup_base=Path("/tmp"),
        )

        runner._parse_log_line("Cloning into 'test-repo'...")

        assert len(runner._log_lines) == 1


class TestCancel:
    """Тесты принудительного прерывания задачи."""

    def test_cancel_no_task(self):
        """Проверка безопасности вызова отмены до инициализации задачи."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=Path("/tmp"),
        )

        runner.cancel()
        assert runner._cancel_flag is True

    def test_cancel_with_process(self):
        """Проверка вызова kill() у процесса при отмене."""
        runner = BackupRunner(
            username="testuser",
            token="ghp_test123",
            backup_base=Path("/tmp"),
        )

        runner._process = MagicMock()
        runner._process.returncode = None

        runner.cancel()

        runner._process.kill.assert_called_once()


class TestRunSync:
    """Тесты синхронной обертки запуска."""

    def test_run_sync_wrapper(self):
        """Проверка вызова asyncio.run для выполнения асинхронного метода run."""
        with patch("core.backup_runner.asyncio.run") as mock_run:
            mock_run.return_value = BackupResult(
                status=BackupStatus.SUCCESS,
                backup_dir=Path("/tmp"),
                start_time=None,  # type: ignore
            )

            runner = BackupRunner(
                username="testuser",
                token="ghp_test123",
                backup_base=Path("/tmp"),
            )

            result = runner.run_sync()

            mock_run.assert_called_once()
            assert result.status == BackupStatus.SUCCESS


class TestRun:
    """Тесты основного асинхронного цикла выполнения бэкапа."""

    @pytest.mark.asyncio
    async def test_run_backup_not_found(self, temp_dir):
        """Обработка ситуации отсутствия исполняемого файла в системе."""
        with patch("core.backup_runner.shutil.which", return_value=False):
            runner = BackupRunner(
                username="testuser",
                token="ghp_test123",
                backup_base=temp_dir,
            )

            result = await runner.run()

            assert result.status == BackupStatus.FAILED
            assert "Не найден" in result.error_message

    @pytest.mark.asyncio
    async def test_run_lock_error(self, temp_dir):
        """Проверка возврата FAILED статуса при обнаружении активной блокировки."""
        lock_file = temp_dir / ".backup.lock"
        lock_file.write_text(str(__import__("os").getpid()))

        with patch("core.backup_runner.shutil.which", return_value=True):
            runner = BackupRunner(
                username="testuser",
                token="ghp_test123",
                backup_base=temp_dir,
            )

            result = await runner.run()

            assert result.status == BackupStatus.FAILED
            assert "Бэкап уже запущен" in result.error_message

        lock_file.unlink()

    @pytest.mark.asyncio
    async def test_run_creates_backup_dir(self, temp_dir):
        """Проверка автоматического создания целевой папки при старте процесса."""
        with patch("core.backup_runner.shutil.which", return_value=True):
            with patch(
                "core.backup_runner.asyncio.create_subprocess_exec"
            ) as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.stdout.readline = AsyncMock(
                    side_effect=[
                        b"",
                    ]
                )
                mock_process.wait = AsyncMock(return_value=0)
                mock_subprocess.return_value = mock_process

                runner = BackupRunner(
                    username="testuser",
                    token="ghp_testtoken12345678901234567890",
                    backup_base=temp_dir,
                )

                await runner.run()

                backup_dirs = [d for d in temp_dir.iterdir() if d.is_dir()]
                assert len(backup_dirs) >= 1
