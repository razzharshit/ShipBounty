from app.models.pull_request import PullRequest
from app.models.pull_request_file import PullRequestFile
from app.models.repository import Repository
from app.models.user import User
from app.models.authorization import Organization
from app.services.pr_file_service import get_files_by_pr_id, synchronize_pr_files


def _create_pr(session_factory) -> int:
    db = session_factory()
    user = User(github_id=1, username="octocat")
    organization = Organization(github_org_id=4, login="acme")
    db.add_all([user, organization])
    db.flush()
    repository = Repository(
        github_repo_id=2,
        organization_id=organization.id,
        name="widgets",
        owner="acme",
        full_name="acme/widgets",
    )
    db.add(repository)
    db.flush()
    pr = PullRequest(
        github_pr_id=3,
        title="Snapshot test",
        author_id=user.id,
        repo_id=repository.id,
    )
    db.add(pr)
    db.commit()
    pr_id = pr.id
    db.close()
    return pr_id


def _file(filename: str, **overrides) -> dict:
    data = {
        "filename": filename,
        "status": "modified",
        "sha": "a" * 40,
        "additions": 2,
        "deletions": 1,
        "changes": 3,
        "patch": "@@ -1 +1 @@",
        "contents_url": "https://api.github.com/content",
        "blob_url": "https://github.com/blob",
        "raw_url": "https://github.com/raw",
    }
    data.update(overrides)
    return data


def test_250_file_snapshot_is_stored(session_factory):
    pr_id = _create_pr(session_factory)
    db = session_factory()
    files = [_file(f"src/file-{index}.py") for index in range(250)]

    assert synchronize_pr_files(db, pr_id, files) == 250
    assert len(get_files_by_pr_id(db, pr_id)) == 250
    db.close()


def test_rename_reconciles_the_old_path(session_factory):
    pr_id = _create_pr(session_factory)
    db = session_factory()
    synchronize_pr_files(db, pr_id, [_file("src/old.py")])
    original_id = db.query(PullRequestFile).one().id

    synchronize_pr_files(
        db,
        pr_id,
        [
            _file(
                "src/new.py",
                status="renamed",
                previous_filename="src/old.py",
            )
        ],
    )

    rows = db.query(PullRequestFile).all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].filename == "src/new.py"
    assert rows[0].previous_filename == "src/old.py"
    assert rows[0].is_current is True
    db.close()


def test_absent_file_becomes_non_current_and_is_hidden(session_factory):
    pr_id = _create_pr(session_factory)
    db = session_factory()
    synchronize_pr_files(db, pr_id, [_file("keep.py"), _file("delete.py")])

    synchronize_pr_files(db, pr_id, [_file("keep.py")])

    assert [row.filename for row in get_files_by_pr_id(db, pr_id)] == ["keep.py"]
    deleted = (
        db.query(PullRequestFile)
        .filter(PullRequestFile.filename == "delete.py")
        .one()
    )
    assert deleted.is_current is False
    assert deleted.removed_at is not None
    db.close()


def test_modified_file_updates_patch_counts_and_missing_patch_reason(session_factory):
    pr_id = _create_pr(session_factory)
    db = session_factory()
    synchronize_pr_files(db, pr_id, [_file("src/app.py")])

    synchronize_pr_files(
        db,
        pr_id,
        [
            _file(
                "src/app.py",
                additions=20,
                deletions=5,
                changes=25,
                patch=None,
                sha="b" * 40,
            )
        ],
    )

    stored = get_files_by_pr_id(db, pr_id)[0]
    assert (stored.additions, stored.deletions, stored.changes) == (20, 5, 25)
    assert stored.sha == "b" * 40
    assert stored.patch is None
    assert stored.patch_available is False
    assert stored.patch_status == "not_returned"
    db.close()
