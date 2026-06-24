"""TUI-приложение: точка входа в интерфейс."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.widgets import Button, Footer, Input, Select

from core.config import Config
from ui.backup import BackupTabContent
from ui.history import HistoryTabContent
from ui.restore import RestoreTabContent
from ui.settings import SettingsTabContent

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TABS = ["backup", "history", "restore", "settings"]


class MainScreen(Container):
    """
    Корневой контейнер. Держит навигацию и переключает вкладки.

    Горячие клавиши: 1-4 — вкладки, q — выход.
    """

    BINDINGS = [
        Binding("q", "quit", "Выход", priority=True),
        Binding("1", "switch_tab('backup')", "Бэкап"),
        Binding("2", "switch_tab('history')", "История"),
        Binding("3", "switch_tab('restore')", "Восстановление"),
        Binding("4", "switch_tab('settings')", "Настройки"),
    ]

    def __init__(self, config: Config | None) -> None:
        super().__init__()
        self._current_tab = "backup"

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            yield Button(
                "🔄 Бэкап",
                id="tab-backup",
                classes="tab-btn -active",
                variant="default",
            )
            yield Button(
                "📋 История", id="tab-history", classes="tab-btn", variant="default"
            )
            yield Button(
                "📥 Восст.", id="tab-restore", classes="tab-btn", variant="default"
            )
            yield Button(
                "⚙️  Настройки", id="tab-settings", classes="tab-btn", variant="default"
            )

        with Container(id="content-area"):
            with ScrollableContainer(id="panel-backup", classes="tab-panel"):
                yield BackupTabContent()

            with ScrollableContainer(id="panel-history", classes="tab-panel"):
                yield HistoryTabContent()

            with ScrollableContainer(id="panel-restore", classes="tab-panel"):
                yield RestoreTabContent()

            with ScrollableContainer(id="panel-settings", classes="tab-panel"):
                yield SettingsTabContent()

        yield Footer()

    def on_mount(self) -> None:
        self._show_tab("backup")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("tab-"):
            self._show_tab(btn_id[4:])

    def action_switch_tab(self, tab_id: str) -> None:
        self._show_tab(tab_id)

    def _show_tab(self, tab_id: str) -> None:
        if tab_id not in TABS:
            return

        self._current_tab = tab_id

        for name in TABS:
            panel = self.query_one(f"#panel-{name}")
            if name == tab_id:
                panel.remove_class("-hidden")
            else:
                panel.add_class("-hidden")

        for name in TABS:
            btn = self.query_one(f"#tab-{name}", Button)
            if name == tab_id:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")

        config = Config.from_env_file(PROJECT_ROOT)

        backup = self.query_one("#panel-backup").query_one(BackupTabContent)
        backup.set_config(config)
        backup.refresh_ui()
        if tab_id == "backup":
            asyncio.create_task(backup._check_rate_limit())

        settings = self.query_one("#panel-settings").query_one(SettingsTabContent)
        settings.set_config(config)
        settings.refresh_ui()

        self.call_later(lambda: self._focus_first_in_tab(tab_id))

    def _focus_first_in_tab(self, tab_id: str) -> None:
        panel = self.query_one(f"#panel-{tab_id}")
        for widget_type in (Input, Button, Select):
            try:
                widget = panel.query(widget_type).first()
                widget.focus()
                return
            except Exception:
                pass


class GHBackupApp(App):
    """Точка входа: монтирую MainScreen и запускаю event loop."""

    CSS_PATH = "app.tcss"
    TITLE = "gh-backup"
    BINDINGS = [Binding("q", "quit", "Выход", priority=True)]

    def on_mount(self) -> None:
        config = Config.from_env_file(PROJECT_ROOT)
        self.mount(MainScreen(config))

    def on_unmount(self) -> None:
        """Очистка при закрытии приложения."""
        from ui.backup import BackupTabContent
        try:
            backup = self.query_one("#panel-backup").query_one(BackupTabContent)
            backup.on_unmount()
        except Exception:
            pass


def main() -> None:
    """Запуск приложения из консоли."""
    app = GHBackupApp()
    app.run()
