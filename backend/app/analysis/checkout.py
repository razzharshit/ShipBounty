from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

import requests

from app.github.auth import get_installation_token


class RepositoryCheckout:
    """Disposable exact-commit archive used only as a read-only analyzer mount."""

    def __init__(
        self,
        *,
        repository_full_name: str,
        head_sha: str,
        installation_id: int,
    ) -> None:
        self.repository_full_name = repository_full_name
        self.head_sha = head_sha
        self.installation_id = installation_id
        self._temporary_directory: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> str:
        token = get_installation_token(self.installation_id)
        response = requests.get(
            (
                "https://api.github.com/repos/"
                f"{self.repository_full_name}/tarball/{self.head_sha}"
            ),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=60,
        )
        response.raise_for_status()
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="gbd-analysis-"
        )
        root = Path(self._temporary_directory.name).resolve()
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            members = []
            for member in archive.getmembers():
                target = (root / member.name).resolve()
                if root not in target.parents and target != root:
                    raise RuntimeError("GitHub archive attempted path traversal")
                if member.issym() or member.islnk() or member.isdev():
                    continue
                members.append(member)
            archive.extractall(root, members=members)
        directories = [item for item in root.iterdir() if item.is_dir()]
        if len(directories) != 1:
            raise RuntimeError("GitHub archive had an unexpected root layout")
        return str(directories[0])

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
