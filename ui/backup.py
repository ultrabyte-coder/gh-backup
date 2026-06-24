"""Вкладка бэкапа: настройка режима, запуск, отображение прогресса."""

from __future__ import annotations

import asyncio
import datetime
import platform
import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Select, Static

from core.backup_runner import (
    BackupMode,
    BackupResult,
    BackupRunner,
    BackupStatus,
)
from core.config import Config
from core.github_api import GitHubAPI
from core.rate_limit import RateLimitGuard
from core.statistics import collect_all_stats, collect_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_BASE = PROJECT_ROOT / "backups"


def _send_notification(title: str, message: str) -> None:
    """Отправка системного уведомления (Linux/macOS/Windows)."""
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.run(
                ["notify-send", title, message],
                timeout=5,
                capture_output=True,
            )
        elif system == "Darwin":
            safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
            safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{safe_message}" with title "{safe_title}"'
            subprocess.run(
                ["osascript", "-e", script],
                timeout=5,
                capture_output=True,
            )
        elif system == "Windows":
            safe_title = title.replace("'", "''")
            safe_message = message.replace("'", "''")
            ps_cmd = (
                f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
                f"[System.Windows.Forms.MessageBox]::Show('{safe_message}', '{safe_title}')"
            )
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                timeout=5,
                capture_output=True,
            )
    except Exception:
        pass


class BackupTabContent(Static):
    """Вкладка настройки и запуска бэкапа."""

    def __init__(self) -> None:
        super().__init__()
        self._config: Config | None = None
        self._runner: BackupRunner | None = None
        self._backup_task: asyncio.Task | None = None

    def set_config(self, config: Config | None) -> None:
        self._config = config

    @property
    def config(self) -> Config | None:
        return self._config or Config.from_env_file(PROJECT_ROOT)

    def refresh_ui(self) -> None:
        cfg = self.config
        try:
            info = self.query_one("#backup-info", Static)
            if cfg:
                info.update(
                    f"Аккаунт: **{cfg.gh_username}**  |  "
                    f"Токен: `{cfg.masked_token()}`  |  "
                    f"Директория: `{BACKUP_BASE}`"
                )
                info.remove_class("error-box")
                info.add_class("card")
                self.query_one("#start-backup", Button).disabled = False
            else:
                info.update(
                    "⚠️  Сначала настройте аккаунт во вкладке «Настройки» (клавиша 4)"
                )
                info.remove_class("card")
                info.add_class("error-box")
                self.query_one("#start-backup", Button).disabled = True
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        cfg = self.config
        yield Static(
            f"Аккаунт: **{cfg.gh_username}**  |  Токен: `{cfg.masked_token()}`  |  Директория: `{BACKUP_BASE}`"
            if cfg
            else "⚠️  Сначала настройте аккаунт во вкладке «Настройки» (клавиша 4)",
            id="backup-info",
            classes="card" if cfg else "error-box",
        )
        with Horizontal(classes="info-row"):
            yield Label("Режим:", classes="info-label")
            yield Select(
                [
                    ("Полный — всё: репо, wiki, issues, PR, gists, releases, forks, labels, milestones, assets, starred", "full"),
                    ("Быстрый — только репо + wiki", "quick"),
                ],
                value="full",
                id="backup-mode",
            )
        with Horizontal(classes="info-row"):
            yield Label("Инкрементально:", classes="info-label")
            yield Select(
                [
                    ("Нет — каждый раз новая директория", False),
                    ("Да — обновлять существующие", True),
                ],
                value=False,
                id="backup-incremental",
            )
        with Horizontal(classes="info-row"):
            yield Button(
                "🚀 Запустить бэкап",
                id="start-backup",
                variant="primary",
                disabled=not cfg,
            )
            yield Button(
                "⏹️ Остановить", id="stop-backup", variant="error", disabled=True
            )
        yield Static("", id="rate-limit-info")
        yield Static("", id="backup-status")

    def on_mount(self) -> None:
        self._update_preview()
        asyncio.create_task(self._check_rate_limit())

    def on_unmount(self) -> None:
        """Очистка при закрытии вкладки."""
        if self._runner:
            self._runner.cancel()
        if self._backup_task and not self._backup_task.done():
            self._backup_task.cancel()

    def _update_preview(self) -> None:
        try:
            stats = collect_all_stats(BACKUP_BASE)
            if stats:
                lines = ["\n[b]Последние бэкапы:[/b]\n"]
                for s in stats[:3]:
                    lines.append(f"  {s.created_at:%Y-%m-%d %H:%M}  {s.summary}")
                self.query_one("#backup-status", Static).update("\n".join(lines))
        except Exception:
            pass

    async def _check_rate_limit(self) -> None:
        """Проверка rate limit при открытии вкладки."""
        cfg = self.config
        if not cfg:
            return

        try:
            api = GitHubAPI(token=cfg.gh_token)
            guard = RateLimitGuard(api)
            status = await guard.check()
            await api.close()

            widget = self.query_one("#rate-limit-info", Static)
            if status.severity == "ok":
                widget.update(
                    f"✅ Rate limit: осталось **{status.remaining}**/{status.limit} "
                    f"({status.usage_percent:.0f}% использовано)"
                )
                widget.remove_class("error-box")
                widget.remove_class("warning-box")
                widget.add_class("card")
                self.query_one("#start-backup", Button).disabled = False
            elif status.severity == "warn":
                widget.update(
                    f"⚠️ Rate limit: осталось **{status.remaining}**/{status.limit} "
                    f"({status.usage_percent:.0f}% использовано)\n"
                    f"  Рекомендуется подождать до сброса: {status.reset_datetime:%H:%M}"
                )
                widget.remove_class("error-box")
                widget.remove_class("card")
                widget.add_class("warning-box")
                self.query_one("#start-backup", Button).disabled = False
            else:
                widget.update(
                    f"[red]{status.message}[/red]\n"
                    f"  Сброс: [b]{status.reset_datetime:%H:%M}[/b]"
                )
                widget.remove_class("card")
                widget.remove_class("warning-box")
                widget.add_class("error-box")
                self.query_one("#start-backup", Button).disabled = True
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-backup":
            await self._start_backup()
        elif event.button.id == "stop-backup":
            self._stop_backup()

    async def _start_backup(self) -> None:
        cfg = self.config
        if not cfg:
            return

        mode_select = self.query_one("#backup-mode", Select)
        incr_select = self.query_one("#backup-incremental", Select)
        mode = BackupMode.FULL if mode_select.value == "full" else BackupMode.QUICK
        incremental = bool(incr_select.value)

        self._runner = BackupRunner(
            username=cfg.gh_username,
            token=cfg.gh_token,
            backup_base=BACKUP_BASE,
            mode=mode,
            incremental=incremental,
        )

        self.query_one("#start-backup", Button).disabled = True
        self.query_one("#stop-backup", Button).disabled = False
        self.query_one("#backup-status", Static).update(
            "[b]⏳ Бэкап выполняется…[/b]\n\n"
            "[dim]Большие репозитории могут загружаться долго.\n"
            "Пожалуйста, наберитесь терпения.[/dim]"
        )
        self.app.refresh()
        self._backup_task = asyncio.create_task(self._run_backup_async())
        self._runner._task = self._backup_task

    async def _run_backup_async(self) -> None:
        try:
            assert self._runner is not None
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._runner.run_sync)
            self._on_backup_done(result)
        except asyncio.CancelledError:
            self._on_backup_done(
                BackupResult(
                    status=BackupStatus.CANCELLED,
                    backup_dir=BACKUP_BASE,
                    start_time=datetime.datetime.now(),
                    error_message="Бэкап отменён пользователем",
                )
            )
        except Exception as e:
            self._on_backup_done(
                BackupResult(
                    status=BackupStatus.FAILED,
                    backup_dir=BACKUP_BASE,
                    start_time=datetime.datetime.now(),
                    error_message=str(e),
                )
            )

    def _stop_backup(self) -> None:
        """Остановка бэкапа."""
        self.query_one("#backup-status", Static).update("[b]⏹️ Остановка…[/b]")
        self.query_one("#start-backup", Button).disabled = True
        self.query_one("#stop-backup", Button).disabled = True
        self.app.refresh()
        if self._runner:
            self._runner.cancel()
        asyncio.get_event_loop().call_later(3, self._force_reset_if_stuck)

    def _force_reset_if_stuck(self) -> None:
        """Сброс UI если _on_backup_done не вызвался."""
        try:
            start_btn = self.query_one("#start-backup", Button)
            if start_btn.disabled:
                self._on_backup_done(
                    BackupResult(
                        status=BackupStatus.CANCELLED,
                        backup_dir=BACKUP_BASE,
                        start_time=datetime.datetime.now(),
                        error_message="Бэкап отменён пользователем",
                    )
                )
        except Exception:
            pass

    def _on_backup_done(self, result: BackupResult) -> None:
        self.query_one("#start-backup", Button).disabled = False
        self.query_one("#stop-backup", Button).disabled = True

        if result.status == BackupStatus.SUCCESS:
            stats = collect_stats(result.backup_dir)
            if stats:
                msg = (
                    f"[b]✅ Бэкап завершён за {result.duration_seconds:.0f}с[/b]\n\n"
                    f"  📦 Репозитории:  {stats.repos}\n"
                    f"  📖 Wiki:          {stats.wikis}\n"
                    f"  📝 Gists:         {stats.gists}\n"
                    f"  💾 Размер:        {stats.total_size}\n"
                    f"  📁 Директория:    {result.backup_dir}"
                )
            else:
                msg = f"[b]✅ Бэкап завершён за {result.duration_seconds:.0f}с[/b]\n  📁 {result.backup_dir}"
            self.query_one("#backup-status", Static).update(msg)
            _send_notification(
                "gh-backup",
                f"Бэкап завершён за {result.duration_seconds:.0f}с",
            )
        elif result.status == BackupStatus.CANCELLED:
            self.query_one("#backup-status", Static).update("[b]⏹️ Бэкап отменён[/b]")
            _send_notification("gh-backup", "Бэкап отменён пользователем")
        else:
            self.query_one("#backup-status", Static).update(
                f"[red][b]❌ Ошибка:[/b] {result.error_message}[/red]"
            )
            _send_notification("gh-backup", f"Ошибка: {result.error_message}")
        self.app.refresh()
        asyncio.create_task(self._check_rate_limit())
