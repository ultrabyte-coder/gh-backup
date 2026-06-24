"""
Подсчёт статистики бэкапа.
Логика замера веса директорий и разбора структуры для вывода отчета.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path


def human_size(path: Path) -> str:
    """Перевод размера директории в читаемый вид (B, KB, MB, GB, TB)."""
    if not path.is_dir():
        return "0 B"

    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except Exception:
        return "0 B"

    size = float(total)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def count_git_dirs(base: Path, pattern: str = "*.git") -> int:
    """Поиск и подсчет директорий по заданному паттерну."""
    if not base.is_dir():
        return 0
    return len(list(base.rglob(pattern)))


@dataclass
class BackupStats:
    """Набор данных по конкретной копии бэкапа."""
    backup_dir: Path
    name: str
    created_at: datetime.datetime
    repos: int = 0
    wikis: int = 0
    gists: int = 0
    total_size: str = "0 B"
    mode: str = "unknown"

    @property
    def summary(self) -> str:
        """Краткая строка состояния для вывода в лог или UI."""
        return f"📦 {self.repos} репо · 📖 {self.wikis} wiki · 📝 {self.gists} gists · 💾 {self.total_size}"


def collect_stats(backup_dir: Path | str) -> BackupStats | None:
    """Сбор метрик для отдельно взятой папки бэкапа."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return None

    name = backup_dir.name

    # Извлечение даты создания из имени папки или через mtime файла
    try:
        # Ожидаемый формат: username-YYYY-MM-DD-HHMMSS
        parts = name.rsplit("-", 3)
        if len(parts) >= 4:
            created = datetime.datetime.strptime(
                f"{parts[-3]}-{parts[-2]}-{parts[-1][:2]} {parts[-1][2:4]}:{parts[-1][4:]}",
                "%Y-%m-%d %H%M%S",
            )
        else:
            created = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime)
    except (ValueError, IndexError):
        created = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime)

    # Анализ репозиториев (наличие .git внутри repository/)
    repos = 0
    repos_dir = backup_dir / "repositories"
    if repos_dir.is_dir():
        for d in repos_dir.iterdir():
            if d.is_dir() and (d / "repository" / ".git").exists():
                repos += 1

    wikis = count_git_dirs(backup_dir / "wikis", "*.git")

    gists_dir = backup_dir / "gists"
    gists = (
        len([d for d in gists_dir.iterdir() if d.is_dir()]) if gists_dir.is_dir() else 0
    )
    # Определение режима (full/quick) по наличию метаданных (issues, pulls и т.д.)
    has_metadata = False
    if repos_dir.is_dir():
        for d in repos_dir.iterdir():
            if d.is_dir():
                if (
                    (d / "issues").exists()
                    or (d / "pulls").exists()
                    or (d / "labels").exists()
                    or (d / "releases").exists()
                ):
                    has_metadata = True
                    break
    mode = "full" if has_metadata else "quick"

    return BackupStats(
        backup_dir=backup_dir,
        name=name,
        created_at=created,
        repos=repos,
        wikis=wikis,
        gists=gists,
        total_size=human_size(backup_dir),
        mode=mode,
    )


def collect_all_stats(backup_base: Path | str) -> list[BackupStats]:
    """Формирование общего списка статистики по всем найденным бэкапам."""
    backup_base = Path(backup_base)
    if not backup_base.is_dir():
        return []

    stats = []
    for entry in sorted(backup_base.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            s = collect_stats(entry)
            if s:
                stats.append(s)

    # Сортировка: свежий бэкап всегда в начале списка
    stats.sort(key=lambda x: x.created_at, reverse=True)
    return stats
