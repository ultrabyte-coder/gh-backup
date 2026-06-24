"""
Безопасное управление конфигами и секретами.
Храню всё в .env, здесь же логика валидации полей и маскировка токенов.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

_ENV_FILENAME = ".env"
# Паттерн для проверки токенов GitHub (классические ghp_ и новые fine-grained)
_TOKEN_PATTERN = re.compile(r"^(ghp_|gho_|ghu_|ghs_|github_pat_|)[A-Za-z0-9_]{36,}$")


class Config(BaseModel):
    """Конфигурация бэкапа. Проверяет данные сразу при загрузке."""

    gh_username: str = Field(..., min_length=1, max_length=39)
    gh_token: str = Field(..., min_length=10)
    backup_dir: str = "backups"

    @field_validator("gh_username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        # Валидация юзернейма по правилам GitHub: буквы, цифры, дефисы.
        # Не может начинаться или заканчиваться на дефис.
        if not re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$", v):
            raise ValueError(
                "Неверный формат username (допустимы буквы, цифры и дефисы)"
            )
        return v

    @field_validator("gh_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Токен не может быть пустым")
        # Базовая проверка структуры, чтобы не подсунуть совсем левую строку
        if not _TOKEN_PATTERN.match(v):
            raise ValueError(
                "Неверный формат токена (должен начинаться с ghp_, gho_, ghu_, ghs_ или github_pat_)"
            )
        return v

    # ------------------------------------------------------------------
    # Работа с файлами — чтение и сохранение настроек
    # ------------------------------------------------------------------

    @classmethod
    def from_env_file(cls, project_root: Path | str | None = None) -> Config | None:
        """Загрузка конфига из .env. Если файла нет или он кривой — возвращаю None."""
        root = Path(project_root) if project_root else Path.cwd()
        env_file = root / _ENV_FILENAME

        if not env_file.is_file():
            return None

        data: dict[str, str] = {}
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Парсинг KEY=VALUE. Кавычки отсекаю.
                match = re.match(r"^(\w+)=['\"]?([^'\"]*?)['\"]?$", line)
                if match:
                    key, value = match.group(1), match.group(2)
                    data[key] = value

        if "GH_USERNAME" not in data or "GH_TOKEN" not in data:
            return None

        return cls(
            gh_username=data["GH_USERNAME"],
            gh_token=data["GH_TOKEN"],
            backup_dir=data.get("BACKUP_DIR", "backups"),
        )

    def save_to_env_file(self, project_root: Path | str | None = None) -> Path:
        """Сохранение конфига в .env с ограничением прав доступа (chmod 600)."""
        root = Path(project_root) if project_root else Path.cwd()
        root.mkdir(parents=True, exist_ok=True)
        env_file = root / _ENV_FILENAME

        content = (
            f"# Конфиг gh-backup — автоматически сгенерирован\n"
            f"# Удалите этот файл чтобы сбросить настройки\n"
            f"GH_USERNAME='{self.gh_username}'\n"
            f"GH_TOKEN='{self.gh_token}'\n"
            f"BACKUP_DIR='{self.backup_dir}'\n"
        )

        # Пишу через временный файл, чтобы не запороть основной при сбое
        tmp_file = env_file.with_suffix(".tmp")
        tmp_file.write_text(content, encoding="utf-8")

        # Доступ только для владельца (важно для токенов)
        os.chmod(tmp_file, 0o600)
        tmp_file.rename(env_file)

        return env_file

    @staticmethod
    def remove_env_file(project_root: Path | str | None = None) -> bool:
        """Удаление .env файла. Возвращает True, если файл успешно снесен."""
        root = Path(project_root) if project_root else Path.cwd()
        env_file = root / _ENV_FILENAME
        if env_file.exists():
            env_file.unlink()
            return True
        return False

    def masked_token(self) -> str:
        """Маскировка токена для вывода в консоль или лог."""
        if len(self.gh_token) <= 8:
            return "****"
        return self.gh_token[:4] + "..." + self.gh_token[-4:]
