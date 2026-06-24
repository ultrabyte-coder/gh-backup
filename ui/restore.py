"""Вкладка восстановления: выбор бэкапа, сканирование, restore и verify."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Select, Static

from core.config import Config
from core.restore import RestoreEngine, RestoreItem, RestoreType
from core.statistics import collect_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_BASE = PROJECT_ROOT / "backups"


class RestoreTabContent(Static):
    """
    Вкладка восстановления.

    Позволяет выбрать бэкап, просканировать его и восстановить данные.
    """

    def __init__(self) -> None:
        super().__init__()
        self._engine: RestoreEngine | None = None
        self._items: list[RestoreItem] = []
        self._selected_backup: Path | None = None

    def compose(self) -> ComposeResult:
        yield Static("Выберите бэкап для восстановления:", classes="card")

        with Horizontal(classes="info-row"):
            yield Label("Бэкап:", classes="info-label")
            yield Select([("— нажмите Обновить —", None)], id="restore-backup-select")

        with Horizontal(classes="info-row"):
            yield Button("📂 Обновить список", id="scan-backup", variant="default")

        yield Static("", id="restore-items-list")

        yield Static(
            "[dim]💡 Чтобы восстановить на другой аккаунт — "
            "смените токен во вкладке ⚙️ Настройки[/dim]",
            classes="hint-text",
        )

        with Horizontal(classes="info-row"):
            yield Button(
                "📥 Восстановить на текущий аккаунт", id="do-restore", variant="primary"
            )
            yield Button("🔍 Проверить", id="do-verify", variant="success")

        yield Static("", id="restore-log")

    def on_mount(self) -> None:
        self._populate_backup_list()

    def _populate_backup_list(self) -> None:
        backups = RestoreEngine.discover_backups(BACKUP_BASE)
        select = self.query_one("#restore-backup-select", Select)
        if not backups:
            select.set_options([("Нет доступных бэкапов", None)])
            return
        options = []
        for d in backups:
            stats = collect_stats(d)
            size = stats.total_size if stats else "?"
            options.append((f"{d.name}  ({size})", d))
        select.set_options(options)
        select.value = backups[0]

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scan-backup":
            self._populate_backup_list()
        elif event.button.id == "do-restore":
            await self._do_restore()
        elif event.button.id == "do-verify":
            await self._do_verify()

    def on_select_changed(self, event: Select.Changed) -> None:
        if (
            event.select.id == "restore-backup-select"
            and event.value is not None
            and event.value is not Select.NULL
        ):
            self._selected_backup = event.value  # type: ignore[assignment]
            self._scan_selected_backup()

    def _scan_selected_backup(self) -> None:
        if not self._selected_backup:
            return
        self._engine = RestoreEngine(token="")
        self._items = RestoreEngine.scan_backup(self._selected_backup)
        if not self._items:
            self.query_one("#restore-items-list", Static).update(
                "\n  📭 В этом бэкапе ничего не найдено.\n"
            )
            return
        lines = [f"\n[b]Найдено {len(self._items)} элементов:[/b]\n"]
        for item in self._items:
            icon = {
                RestoreType.REPOSITORY: "📦",
                RestoreType.WIKI: "📖",
                RestoreType.GIST: "📝",
                RestoreType.ACCOUNT_DATA: "👤",
            }.get(item.restore_type, "❓")
            lines.append(f"  {icon} [{item.restore_type.value}] {item.name}")
        self.query_one("#restore-items-list", Static).update("\n".join(lines))

    async def _do_restore(self) -> None:
        config = Config.from_env_file(PROJECT_ROOT)
        if not config:
            self.query_one("#restore-log", Static).update(
                "[red]⚠️  Сначала настройте аккаунт во вкладке «Настройки»[/red]"
            )
            return

        self._engine = RestoreEngine(token=config.gh_token)
        log = self.query_one("#restore-log", Static)
        lines = [
            f"[b]📥 Восстановление → [green]{config.gh_username}[/green][/b]",
            "",
            "[dim]💡 Чтобы восстановить на другой аккаунт — смените токен в ⚙️ Настройках[/dim]",
        ]
        log.update("\n".join(lines))
        self.app.refresh()

        for item in self._items:
            lines.append(f"\n  ⏳ {item.restore_type.value}: {item.name}")
            log.update("\n".join(lines))

            if item.restore_type == RestoreType.REPOSITORY:
                result = await self._engine.restore_repository(
                    mirror_path=item.path,
                    repo_name=item.name,
                    target_user=config.gh_username,
                )
            elif item.restore_type == RestoreType.WIKI:
                result = await self._engine.restore_wiki(
                    mirror_path=item.path,
                    wiki_name=item.name,
                    target_user=config.gh_username,
                )
            elif item.restore_type == RestoreType.GIST:
                result = await self._engine.restore_gist(
                    gist_path=item.path, gist_id=item.name
                )
            elif item.restore_type == RestoreType.ACCOUNT_DATA:
                lines.append(
                    f"  [dim]⏭️ {item.name} — данные аккаунта (только для справки)[/dim]"
                )
                continue
            else:
                lines.append(f"  [dim]⏭️ {item.name} — неподдерживаемый тип[/dim]")
                continue

            if result.success:
                lines.append(f"  [green]✅ {item.name} — OK[/green]")
            else:
                lines.append(f"  [red]❌ {item.name} — {result.error_message}[/red]")
            log.update("\n".join(lines))
            self.app.refresh()

        lines.append("\n[b]🎉 Восстановление завершено[/b]")
        log.update("\n".join(lines))
        self.app.refresh()

    async def _do_verify(self) -> None:
        if not self._items:
            self.query_one("#restore-log", Static).update(
                "[red]⚠️  Сначала выберите и просканируйте бэкап[/red]"
            )
            return

        log = self.query_one("#restore-log", Static)
        lines = ["[b]🔍 Проверка целостности бэкапа (без push на GitHub)[/b]"]

        total_ok = 0
        total_fail = 0

        for item in self._items:
            if item.restore_type == RestoreType.ACCOUNT_DATA:
                try:
                    with open(item.path, "r") as f:
                        data = json.load(f)
                    count = len(data) if isinstance(data, list) else 1
                    lines.append(f"  [green]✅ {item.name}: {count} записей[/green]")
                    total_ok += 1
                except Exception as e:
                    lines.append(f"  [red]❌ {item.name}: {e}[/red]")
                    total_fail += 1
                continue

            if item.restore_type not in (
                RestoreType.REPOSITORY,
                RestoreType.WIKI,
                RestoreType.GIST,
            ):
                continue

            lines.append(f"\n  ⏳ {item.name} ({item.restore_type.value})...")
            log.update("\n".join(lines))
            self.app.refresh()
            result = await RestoreEngine.verify_repository(
                mirror_path=item.path,
                repo_name=item.name,
            )

            if result.success:
                lines.append(f"  [green]✅ {item.name} — OK[/green]")
                for line in result.log_lines:
                    lines.append(f"    [dim]{line[:120]}[/dim]")
                total_ok += 1
            else:
                lines.append(f"  [red]❌ {item.name} — {result.error_message}[/red]")
                total_fail += 1
            log.update("\n".join(lines))
            self.app.refresh()

        lines.append(f"\n[b]Итого: ✅ {total_ok} OK, ❌ {total_fail} FAILED[/b]")
        log.update("\n".join(lines))
        self.app.refresh()
