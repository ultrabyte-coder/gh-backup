"""
Модуль для восстановления данных из бэкапов.
Работает через git --mirror: сначала клон из локального бэкапа, 
потом пуш в целевой репозиторий.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class RestoreType(Enum):
    REPOSITORY = "repository"
    WIKI = "wiki"
    GIST = "gist"
    ACCOUNT_DATA = "account"


@dataclass
class RestoreItem:
    """Описание конкретной сущности, которая найдена в бэкапе."""
    name: str
    path: Path
    restore_type: RestoreType


@dataclass
class RestoreResult:
    """Отчет по итогам восстановления (или проверки) объекта."""

    name: str
    success: bool
    error_message: str = ""
    log_lines: list[str] = field(default_factory=list)


class RestoreEngine:
    """
    Движок восстановления. Основная фишка — умеет сканить структуру 
    папок бэкапа и восстанавливать репы через временные mirror-клоны.
    """

    def __init__(self, token: str) -> None:
        self.token = token.strip()

    @staticmethod
    def discover_backups(backup_dir: Path | str) -> list[Path]:
        """Поиск всех папок бэкапов. Сортировка по дате изменения, свежие — сверху."""
        backup_dir = Path(backup_dir)
        if not backup_dir.is_dir():
            return []
        return sorted(
            [
                d
                for d in backup_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    @staticmethod
    def scan_backup(backup_dir: Path | str) -> list[RestoreItem]:
        """
        Полный скан папки бэкапа. 
        Разбор по категориям: репозитории, вики, гисты и данные аккаунта.
        """
        backup_dir = Path(backup_dir)
        items: list[RestoreItem] = []

        # Репозитории (лежать должны в repositories/имя/repository/.git)
        repos_dir = backup_dir / "repositories"
        if repos_dir.is_dir():
            for d in sorted(repos_dir.iterdir()):
                if d.is_dir():
                    repo_git = d / "repository" / ".git"
                    if repo_git.exists():
                        items.append(
                            RestoreItem(
                                name=d.name,
                                path=d,
                                restore_type=RestoreType.REPOSITORY,
                            )
                        )

        # Вики (имена папок заканчиваются на .wiki.git)
        wikis_dir = backup_dir / "wikis"
        if wikis_dir.is_dir():
            for d in sorted(wikis_dir.iterdir()):
                if d.is_dir() and d.name.endswith(".wiki.git"):
                    name = d.name[:-9]
                    items.append(
                        RestoreItem(
                            name=name,
                            path=d,
                            restore_type=RestoreType.WIKI,
                        )
                    )

        # Гисты (просто папки с ID гиста)
        gists_dir = backup_dir / "gists"
        if gists_dir.is_dir():
            for d in sorted(gists_dir.iterdir()):
                if d.is_dir():
                    items.append(
                        RestoreItem(
                            name=d.name,
                            path=d,
                            restore_type=RestoreType.GIST,
                        )
                    )

        # Метаданные аккаунта (JSON-файлы со списками фолловеров и т.д.)
        account_dir = backup_dir / "account"
        if account_dir.is_dir():
            for f in sorted(account_dir.glob("*.json")):
                name = f.stem  # followers, following, starred, watched
                items.append(
                    RestoreItem(
                        name=f"account/{name}",
                        path=f,
                        restore_type=RestoreType.ACCOUNT_DATA,
                    )
                )

        return items

    async def restore_repository(
        self,
        mirror_path: Path,
        repo_name: str,
        target_user: str,
        token: str | None = None,
    ) -> RestoreResult:
        """
        Восстановление репозитория. 
        Схема: локальный mirror -> временная папка -> пуш в GitHub.
        """
        tok = token or self.token
        log_lines: list[str] = []

        # Пытаюсь найти корень гит-директории в бэкапе
        actual_mirror = mirror_path / "repository"
        if not (actual_mirror / ".git").exists():
            actual_mirror = (
                mirror_path
            )

        # Формирование URL с токеном для пуша
        remote_url = (
            f"https://x-access-token:{tok}@github.com/{target_user}/{repo_name}.git"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "restore.git"

            # Делаю промежуточный клон-миррор
            clone_cmd = ["git", "clone", "--mirror", str(actual_mirror), str(tmp_path)]
            proc = await asyncio.create_subprocess_exec(
                *clone_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            output = out.decode("utf-8", errors="replace")
            log_lines.append(output)

            if proc.returncode != 0:
                return RestoreResult(
                    name=repo_name,
                    success=False,
                    error_message=f"git clone --mirror failed: {output}",
                    log_lines=log_lines,
                )

            # Пуш всего в целевой репозиторий
            push_cmd = ["git", "-C", str(tmp_path), "push", "--mirror", remote_url]
            proc = await asyncio.create_subprocess_exec(
                *push_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            output = out.decode("utf-8", errors="replace")
            log_lines.append(output)

            if proc.returncode != 0:
                return RestoreResult(
                    name=repo_name,
                    success=False,
                    error_message=f"git push --mirror failed: {output}",
                    log_lines=log_lines,
                )

        return RestoreResult(
            name=repo_name,
            success=True,
            log_lines=log_lines,
        )

    async def restore_wiki(
        self,
        mirror_path: Path,
        wiki_name: str,
        target_user: str,
        token: str | None = None,
    ) -> RestoreResult:
        """Восстановление вики (по сути то же самое, что и репозиторий)."""
        return await self.restore_repository(
            mirror_path=mirror_path,
            repo_name=f"{wiki_name}.wiki",
            target_user=target_user,
            token=token,
        )

    async def restore_gist(
        self,
        gist_path: Path,
        gist_id: str,
        token: str | None = None,
    ) -> RestoreResult:
        """Восстановление гиста через зеркальный пуш."""
        tok = token or self.token
        log_lines: list[str] = []
        remote_url = f"https://x-access-token:{tok}@gist.github.com/{gist_id}.git"

        push_cmd = ["git", "-C", str(gist_path), "push", "--mirror", remote_url]
        proc = await asyncio.create_subprocess_exec(
            *push_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        output = out.decode("utf-8", errors="replace")
        log_lines.append(output)

        if proc.returncode != 0:
            return RestoreResult(
                name=gist_id,
                success=False,
                error_message=f"git push failed: {output}",
                log_lines=log_lines,
            )

        return RestoreResult(
            name=gist_id,
            success=True,
            log_lines=log_lines,
        )

    @staticmethod
    async def verify_repository(mirror_path: Path, repo_name: str) -> RestoreResult:
        """
        Проверка целостности объектов в бэкапе (без отправки в сеть).
        Делаю fsck, смотрю список веток и прикидываю итоговый размер.
        """
        log_lines: list[str] = []
        tmp_dir: str | None = None
        fsck_ok = False

        try:
            actual_mirror = mirror_path / "repository"
            if not (actual_mirror / ".git").exists():
                actual_mirror = mirror_path

            tmp_dir = tempfile.mkdtemp(prefix=f"gh-verify-{repo_name}-")
            tmp_path = Path(tmp_dir) / "verify.git"

            # Сначала клонирую для проверки
            clone_cmd = ["git", "clone", "--mirror", str(actual_mirror), str(tmp_path)]
            proc = await asyncio.create_subprocess_exec(
                *clone_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            output = out.decode("utf-8", errors="replace")
            log_lines.append(f"[clone] {output.strip()}")

            if proc.returncode != 0:
                return RestoreResult(
                    name=repo_name,
                    success=False,
                    error_message=f"clone --mirror failed: {output}",
                    log_lines=log_lines,
                )

            # Проверка целостности через fsck
            fsck_cmd = ["git", "-C", str(tmp_path), "fsck", "--no-dangling"]
            proc = await asyncio.create_subprocess_exec(
                *fsck_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            output = out.decode("utf-8", errors="replace")
            log_lines.append(f"[fsck] {output.strip()[:500]}")
            fsck_ok = proc.returncode == 0

            # Сбор статистики по веткам и тегам
            for cmd, label in [(["branch", "-a"], "branches"), (["tag"], "tags")]:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "-C",
                    str(tmp_path),
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await proc.communicate()
                items = out.decode("utf-8", errors="replace").strip().split("\n")
                items = [i.strip() for i in items if i.strip()]
                log_lines.append(
                    f"[{label}] {len(items)} found: {', '.join(items[:10])}"
                )

            # Подсчет веса папки
            du_cmd = ["du", "-sh", str(tmp_path)]
            proc = await asyncio.create_subprocess_exec(
                *du_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            size = (
                out.decode("utf-8", errors="replace").split()[0]
                if proc.returncode == 0
                else "?"
            )
            log_lines.append(f"[size] {size}")

            return RestoreResult(
                name=repo_name,
                success=fsck_ok,
                error_message="" if fsck_ok else "git fsck failed — объекты повреждены",
                log_lines=log_lines,
            )

        except Exception as e:
            return RestoreResult(
                name=repo_name,
                success=False,
                error_message=str(e),
                log_lines=log_lines,
            )

        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
