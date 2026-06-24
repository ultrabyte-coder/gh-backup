"""Вкладка настроек: ввод username/token, проверка через API, сохранение в .env."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static

from core.config import Config
from core.github_api import (
    GitHubAPI,
    InvalidTokenError,
    UserNotFoundError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SettingsTabContent(Static):
    """
    Вкладка настроек: ввод токена, проверка, сохранение в .env.

    После сохранения — конфиг сразу применяется ко всему приложению.
    """

    def __init__(self) -> None:
        super().__init__()
        self._config: Config | None = None

    def set_config(self, config: Config | None) -> None:
        self._config = config

    def refresh_ui(self) -> None:
        cfg = self._config or Config.from_env_file(PROJECT_ROOT)
        try:
            banner = self.query_one("#settings-banner", Static)
            if cfg:
                banner.update(
                    f"✅ Конфиг загружен для **{cfg.gh_username}**\nТокен: `{cfg.masked_token()}`"
                )
                banner.remove_class("error-box")
                banner.add_class("success-box")
                self.query_one("#settings-username", Input).value = cfg.gh_username
                self.query_one("#settings-token", Input).value = cfg.gh_token
            else:
                banner.update("⚠️ Конфиг не найден. Заполните форму ниже.")
                banner.remove_class("success-box")
                banner.add_class("error-box")
                self.query_one("#settings-username", Input).value = ""
                self.query_one("#settings-token", Input).value = ""
            self.query_one("#settings-status", Static).update("")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        cfg = self._config or Config.from_env_file(PROJECT_ROOT)
        yield Static(
            f"✅ Конфиг загружен для **{cfg.gh_username}**\nТокен: `{cfg.masked_token()}`"
            if cfg
            else "⚠️ Конфиг не найден. Заполните форму ниже.",
            id="settings-banner",
            classes="success-box" if cfg else "error-box",
        )
        yield Static("[b]GitHub Username[/b]", classes="card")
        yield Input(
            placeholder="например: octocat",
            id="settings-username",
            value=cfg.gh_username if cfg else "",
        )
        yield Static("[b]Personal Access Token[/b]", classes="card")
        yield Input(
            placeholder="ghp_xxxxxxxxxxxx или github_pat_xxxx",
            id="settings-token",
            password=True,
            value=cfg.gh_token if cfg else "",
        )
        yield Static(
            "📌 Создать токен: https://github.com/settings/tokens\n"
            "Разрешения: [b]repo[/b], [b]gist[/b], [b]read:org[/b]",
            classes="card",
        )
        with Horizontal(classes="info-row"):
            yield Button(
                "✅ Проверить и сохранить", id="settings-save", variant="primary"
            )
            yield Button("🗑️ Сбросить конфиг", id="settings-reset", variant="error")
        yield Static("", id="settings-status")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            await self._save_settings()
        elif event.button.id == "settings-reset":
            self._reset_settings()

    async def _save_settings(self) -> None:
        username = self.query_one("#settings-username", Input).value.strip()
        token = self.query_one("#settings-token", Input).value.strip()
        status = self.query_one("#settings-status", Static)

        if not username or not token:
            status.update("[red]❌ Заполните все поля[/red]")
            return

        try:
            config = Config(gh_username=username, gh_token=token)
        except Exception as e:
            status.update(f"[red]❌ Ошибка валидации: {e}[/red]")
            return

        status.update("[yellow]⏳ Проверка через GitHub API...[/yellow]")

        api = GitHubAPI(token=config.gh_token)
        try:
            result = await api.validate_all(config.gh_username)
            await api.close()
            config.save_to_env_file(PROJECT_ROOT)
            self._config = config

            token_user = result["token_user"]
            target_user = result["target_user"]
            rate = result["rate_limit"]

            msg = (
                f"\n[b]✅ Всё в порядке![/b]\n\n"
                f"  Токен: пользователь [b]{token_user.login}[/b]\n"
                f"  Цель: [b]{target_user.login}[/b] "
                f"({target_user.public_repos} публичных репо)\n"
                f"  Rate limit: {rate.remaining}/{rate.limit}\n\n"
                f"  Конфиг сохранён в [b].env[/b] (права 600)\n"
            )
            status.update(msg)
            try:
                from ui.backup import BackupTabContent

                backup = self.app.query_one("#panel-backup").query_one(BackupTabContent)
                backup.set_config(config)
                backup.refresh_ui()
            except Exception:
                pass
            self.app.refresh()

        except InvalidTokenError:
            status.update("[red]❌ Токен невалиден или отозван[/red]")
        except UserNotFoundError as e:
            status.update(f"[red]❌ {e}[/red]")
        except Exception as e:
            status.update(f"[red]❌ Ошибка: {e}[/red]")

    def _reset_settings(self) -> None:
        Config.remove_env_file(PROJECT_ROOT)
        self._config = None
        self.refresh_ui()
