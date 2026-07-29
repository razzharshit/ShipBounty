from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.pull_request_file import PullRequestFile


logger = logging.getLogger(__name__)

PATCH_AVAILABLE = "available"
PATCH_BINARY = "binary"
PATCH_TOO_LARGE = "too_large"
PATCH_NOT_RETURNED = "not_returned"
PATCH_STATUSES = {
    PATCH_AVAILABLE,
    PATCH_BINARY,
    PATCH_TOO_LARGE,
    PATCH_NOT_RETURNED,
}


def get_files_by_pr_id(db: Session, pr_id: int) -> list[PullRequestFile]:
    files = (
        db.query(PullRequestFile)
        .filter(
            PullRequestFile.pr_id == pr_id,
            PullRequestFile.is_current.is_(True),
        )
        .order_by(PullRequestFile.filename)
        .all()
    )
    logger.info("Found %s current files for PR %s", len(files), pr_id)
    return files


def _patch_status(file_data: dict) -> str:
    if file_data.get("patch") is not None:
        return PATCH_AVAILABLE
    explicit_status = str(file_data.get("patch_status") or "").lower()
    if explicit_status in PATCH_STATUSES:
        return explicit_status
    if file_data.get("binary") is True:
        return PATCH_BINARY
    # GitHub does not distinguish binary, oversized, and other omissions in this
    # response. Keep the honest default unless another fetch proves the reason.
    return PATCH_NOT_RETURNED


def synchronize_pr_files(
    db: Session,
    pr_id: int,
    files_data: list[dict],
    *,
    commit: bool = True,
) -> int:
    """Apply a complete GitHub file snapshot, retaining non-current audit rows."""
    now = datetime.utcnow()
    existing_rows = (
        db.query(PullRequestFile)
        .filter(PullRequestFile.pr_id == pr_id)
        .all()
    )
    by_filename = {row.filename: row for row in existing_rows}
    seen_row_ids: set[int] = set()
    desired_filenames: set[str] = set()

    for file_data in files_data:
        filename = str(file_data.get("filename") or "")
        if not filename:
            continue
        if filename in desired_filenames:
            raise ValueError(f"Duplicate filename in GitHub snapshot: {filename}")
        desired_filenames.add(filename)

        previous_filename = file_data.get("previous_filename")
        github_status = str(file_data.get("status") or "modified").lower()
        stored = by_filename.get(filename)

        if (
            stored is None
            and github_status == "renamed"
            and previous_filename
        ):
            stored = by_filename.get(str(previous_filename))
            if stored is not None:
                by_filename.pop(stored.filename, None)
                stored.filename = filename
                by_filename[filename] = stored

        if stored is None:
            stored = PullRequestFile(
                pr_id=pr_id,
                filename=filename,
                first_seen_at=now,
            )
            db.add(stored)
            db.flush()
            by_filename[filename] = stored

        stored.previous_filename = (
            str(previous_filename) if previous_filename else None
        )
        stored.github_status = github_status
        stored.sha = file_data.get("sha")
        stored.additions = int(file_data.get("additions") or 0)
        stored.deletions = int(file_data.get("deletions") or 0)
        stored.changes = int(
            file_data.get("changes")
            or stored.additions + stored.deletions
        )
        stored.patch = file_data.get("patch")
        stored.patch_available = stored.patch is not None
        stored.patch_status = _patch_status(file_data)
        stored.contents_url = file_data.get("contents_url")
        stored.blob_url = file_data.get("blob_url")
        stored.raw_url = file_data.get("raw_url")
        stored.last_seen_at = now
        stored.is_current = True
        stored.removed_at = None
        seen_row_ids.add(stored.id)

    for stored in existing_rows:
        if stored.id not in seen_row_ids and stored.is_current:
            stored.is_current = False
            stored.removed_at = now

    if commit:
        db.commit()
    else:
        db.flush()
    return len(desired_filenames)


def save_pr_files(db: Session, pr_id: int, files_data: list[dict]) -> int:
    """Backward-compatible alias; callers must provide a complete snapshot."""
    return synchronize_pr_files(db, pr_id, files_data)
