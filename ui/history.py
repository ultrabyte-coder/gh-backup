"""Вкладка истории бэкапов: таблица с датами, размерами и режимами."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Button, Static

from core.statistics import collect_all_stats

BACKUP_BASE = Path(__file__).resolve().parent.parent / "backups"


class HistoryTabContent(Static):
    """Простая таблица с историей бэкапов."""

    def compose(self) -> ComposeResult:
        yield Button("🔄 Обновить", id="refresh-history", variant="default")
        yield Static("", id="history-content")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-history":
            self._refresh()

    def _refresh(self) -> None:
        stats = collect_all_stats(BACKUP_BASE)
        widget = self.query_one("#history-content", Static)
        if not stats:
            widget.update(
                "\n  📭 Бэкапов пока нет. "
                "Перейдите во вкладку «Бэкап» и запустите первый.\n"
            )
            return

        lines = [
            "\n[b]История бэкапов[/b]\n",
            f"{'Дата':<20} {'Репо':>6} {'Wiki':>6} {'Gists':>6} {'Размер':>10} {'Режим':>8}",
            "─" * 64,
        ]
        for s in stats:
            lines.append(
                f"{s.created_at:%Y-%m-%d %H:%M}  "
                f"{s.repos:>6}  {s.wikis:>6}  {s.gists:>6}  "
                f"{s.total_size:>10}  {s.mode:>8}"
            )
        lines.append(f"\n  Всего бэкапов: [b]{len(stats)}[/b]")
        if stats:
            lines.append(f"  Последний: [b]{stats[0].name}[/b]")
        widget.update("\n".join(lines))
