"""
Обертка для запуска python-github-backup.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_VENV_BIN = Path(sys.executable).parent / "github-backup"
if _VENV_BIN.is_file():
    GITHUB_BACKUP_BIN = str(_VENV_BIN)
else:
    GITHUB_BACKUP_BIN = "github-backup"

LOG_FILENAME = "backup.log"


class BackupMode(Enum):
    FULL = "full"
    QUICK = "quick"


class BackupStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackupResult:
    """Итоговая структура с результатами прогона."""
    status: BackupStatus
    backup_dir: Path
    start_time: datetime.datetime
    end_time: datetime.datetime | None = None
    duration_seconds: float = 0.0
    error_message: str = ""
    log_lines: list[str] = field(default_factory=list)


class BackupRunner:
    """Класс для управления процессом бэкапа."""

    def __init__(
        self,
        username: str,
        token: str,
        backup_base: Path,
        mode: BackupMode = BackupMode.FULL,
        incremental: bool = False,
    ) -> None:
        self.username = username
        self.token = token
        self.backup_base = Path(backup_base)
        self.mode = mode
        self.incremental = incremental
        self._lock_file: Path | None = None
        self._log_lines: list[str] = []
        self._log_file: Path | None = None
        self._logger: logging.Logger | None = None
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._cancel_flag: bool = False

    def _setup_logger(self, backup_dir: Path) -> None:
        """Настройка логгера для записи в файл backup.log."""
        self._log_file = self.backup_base / LOG_FILENAME
        self._logger = logging.getLogger(f"gh-backup.{id(self)}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        handler = logging.FileHandler(self._log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        self._logger.addHandler(handler)

    def _log(self, message: str, level: str = "info") -> None:
        """Запись строки в лог-файл."""
        if self._logger:
            getattr(self._logger, level, self._logger.info)(message)

    def _make_backup_dir(self) -> Path:
        """Создание папки с таймстампом."""
        now = datetime.datetime.now()
        ts = now.strftime("%Y-%m-%d-%H%M%S")
        return self.backup_base / f"{self.username}-{ts}"

    def _find_latest_backup(self) -> Path | None:
        """Поиск последней существующей папки бэкапа для инкрементального обновления."""
        if not self.backup_base.is_dir():
            return None
        candidates = sorted(
            [
                d
                for d in self.backup_base.iterdir()
                if d.is_dir() and d.name.startswith(f"{self.username}-")
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _get_backup_dir(self) -> Path:
        """Определение папки для бэкапа: инкрементально — существующая, иначе — новая."""
        if self.incremental:
            existing = self._find_latest_backup()
            if existing:
                return existing
        return self._make_backup_dir()

    def _build_command(self, backup_dir: Path) -> list[str]:
        """Сборка параметров для CLI в зависимости от режима."""
        cmd = [
            GITHUB_BACKUP_BIN,
            self.username,
            "-t",
            self.token,
            "-o",
            str(backup_dir),
        ]

        if self.mode == BackupMode.QUICK:
            cmd += ["--private", "--repositories", "--wikis"]
        else:
            cmd += [
                "--all",
                "--private",
                "--fork",
                "--gists",
                "--starred-gists",
                "--starred",
                "--pull-details",
                "--assets",
                "--attachments",
            ]

        if self.incremental:
            cmd.append("--incremental")

        cmd += ["--throttle-limit", "200", "--throttle-pause", "15"]

        return cmd

    def _acquire_lock(self) -> None:
        """Защита от повторного запуска."""
        self._lock_file = self.backup_base / ".backup.lock"
        if self._lock_file.exists():
            try:
                pid = int(self._lock_file.read_text().strip())
                os.kill(pid, 0)
                raise LockError(f"Бэкап уже запущен (PID {pid})")
            except (ValueError, ProcessLookupError):
                self._lock_file.unlink(missing_ok=True)

        self._lock_file.write_text(str(os.getpid()))

    def cancel(self) -> None:
        """Остановка задачи через UI."""
        self._cancel_flag = True
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
            except ProcessLookupError:
                pass
        if hasattr(self, "_task") and self._task and not self._task.done():
            self._task.cancel()

    def _release_lock(self) -> None:
        """Удаление лок-файла."""
        if self._lock_file and self._lock_file.exists():
            self._lock_file.unlink(missing_ok=True)

    def _parse_log_line(self, line: str) -> None:
        """Запись строки вывода в лог."""
        self._log_lines.append(line)
        self._log(line)

    def run_sync(self) -> BackupResult:
        """Синхронный запуск."""
        return asyncio.run(self.run())

    async def run(self) -> BackupResult:
        """Основной метод бэкапа."""
        start_time = datetime.datetime.now()
        self._log_lines = []
        self._cancel_flag = False
        self._process = None

        if not shutil.which(GITHUB_BACKUP_BIN):
            return BackupResult(
                status=BackupStatus.FAILED,
                backup_dir=self.backup_base,
                start_time=start_time,
                error_message=(
                    f"Не найден '{GITHUB_BACKUP_BIN}'. "
                    f"Установите: pip install python-github-backup"
                ),
            )

        try:
            self._acquire_lock()
        except LockError as e:
            return BackupResult(
                status=BackupStatus.FAILED,
                backup_dir=self.backup_base,
                start_time=start_time,
                error_message=str(e),
            )

        backup_dir = self._get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logger(backup_dir)
        self._log(f"Бэкап начат: {self.username} ({self.mode.value})", "info")
        self._log(f"Папка: {backup_dir}", "info")

        cmd = self._build_command(backup_dir)
        process: asyncio.subprocess.Process | None = None

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(backup_dir),
            )
            self._process = process

            if process.stdout is None:
                raise RuntimeError("stdout is None")

            async def read_output() -> list[str]:
                assert process.stdout is not None
                lines: list[str] = []
                while True:
                    if self._cancel_flag:
                        break
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").rstrip()
                    lines.append(line)
                    self._parse_log_line(line)
                return lines

            _ = await read_output()
            return_code = await process.wait()
            end_time = datetime.datetime.now()

            if self._cancel_flag:
                self._log("Бэкап отменён пользователем", "warning")
                result = BackupResult(
                    status=BackupStatus.CANCELLED,
                    backup_dir=backup_dir,
                    start_time=start_time,
                    end_time=end_time,
                    duration_seconds=(end_time - start_time).total_seconds(),
                    error_message="Бэкап отменён пользователем",
                    log_lines=list(self._log_lines),
                )
            elif return_code == 0:
                self._log(f"Бэкап завершён успешно за {(end_time - start_time).total_seconds():.0f}с", "info")
                result = BackupResult(
                    status=BackupStatus.SUCCESS,
                    backup_dir=backup_dir,
                    start_time=start_time,
                    end_time=end_time,
                    duration_seconds=(end_time - start_time).total_seconds(),
                    log_lines=list(self._log_lines),
                )
            else:
                self._log(f"Бэкап завершился с ошибкой (код {return_code})", "error")
                result = BackupResult(
                    status=BackupStatus.FAILED,
                    backup_dir=backup_dir,
                    start_time=start_time,
                    end_time=end_time,
                    duration_seconds=(end_time - start_time).total_seconds(),
                    error_message=f"Процесс завершился с кодом {return_code}",
                    log_lines=list(self._log_lines),
                )

        except asyncio.CancelledError:
            end_time = datetime.datetime.now()
            if process:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
            self._log("Бэкап отменён пользователем", "warning")
            result = BackupResult(
                status=BackupStatus.CANCELLED,
                backup_dir=backup_dir,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=(end_time - start_time).total_seconds(),
                error_message="Бэкап отменён пользователем",
                log_lines=list(self._log_lines),
            )

        finally:
            self._release_lock()
            self._process = None

        return result


class LockError(Exception):
    """Исключение при конфликте запусков."""
    pass
