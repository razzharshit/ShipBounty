import pytest

from app.models.pull_request import PullRequestState, ReviewState
from app.services.webhook_sync_service import _lifecycle_state, _review_state


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"state": "open", "draft": True, "merged": False}, PullRequestState.DRAFT),
        ({"state": "open", "draft": False, "merged": False}, PullRequestState.OPEN),
        ({"state": "closed", "draft": False, "merged": False}, PullRequestState.CLOSED),
        ({"state": "closed", "draft": False, "merged": True}, PullRequestState.MERGED),
    ],
)
def test_lifecycle_state(payload, expected):
    assert _lifecycle_state(payload) == expected


def test_review_state_precedence():
    assert _review_state({}, []) == ReviewState.NOT_REQUESTED
    assert _review_state({"requested_reviewers": [{"id": 1}]}, []) == ReviewState.UNDER_REVIEW
    assert (
        _review_state({}, [{"id": 1, "user": {"id": 10}, "state": "APPROVED"}])
        == ReviewState.APPROVED
    )
    assert (
        _review_state(
            {},
            [
                {"id": 1, "user": {"id": 10}, "state": "APPROVED"},
                {"id": 2, "user": {"id": 20}, "state": "CHANGES_REQUESTED"},
            ],
        )
        == ReviewState.CHANGES_REQUESTED
    )
