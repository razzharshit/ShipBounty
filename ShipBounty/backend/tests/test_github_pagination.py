from urllib.parse import parse_qs, urlparse

from app.github import client


class FakeResponse:
    def __init__(self, data, *, next_url=None, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ""
        self.links = {"next": {"url": next_url}} if next_url else {}

    def json(self):
        return self._data


def _file(index: int) -> dict:
    return {
        "filename": f"src/file-{index}.py",
        "status": "modified",
        "sha": f"{index:040x}",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "patch": "@@ -1 +1 @@",
    }


def test_pr_files_follows_link_headers_and_fetches_250_files(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append((url, params))
        page = int((params or {}).get("page") or parse_qs(urlparse(url).query)["page"][0])
        start = (page - 1) * 100
        count = 50 if page == 3 else 100
        next_url = (
            f"https://api.github.com/repos/acme/widgets/pulls/7/files?per_page=100&page={page + 1}"
            if page < 3
            else None
        )
        return FakeResponse([_file(i) for i in range(start, start + count)], next_url=next_url)

    monkeypatch.setattr(client.requests, "get", fake_get)
    snapshot = client.get_pr_files("acme/widgets", 7, "token")

    assert len(snapshot.files) == 250
    assert snapshot.limit_reached is False
    assert calls[0][1] == {"per_page": 100, "page": 1}
    assert calls[1][0].endswith("page=2")
    assert calls[1][1] is None
    assert calls[2][0].endswith("page=3")


def test_pr_files_marks_the_3000_file_cap(monkeypatch):
    def fake_get(url, headers, params, timeout):
        page = int((params or {}).get("page") or parse_qs(urlparse(url).query)["page"][0])
        next_url = (
            f"https://api.github.com/repos/acme/widgets/pulls/7/files?per_page=100&page={page + 1}"
        )
        start = (page - 1) * 100
        return FakeResponse([_file(i) for i in range(start, start + 100)], next_url=next_url)

    monkeypatch.setattr(client.requests, "get", fake_get)
    snapshot = client.get_pr_files("acme/widgets", 7, "token")

    assert len(snapshot.files) == 3000
    assert snapshot.limit_reached is True


def test_exact_multiple_uses_one_fallback_page_without_repeating(monkeypatch):
    requested_pages = []

    def fake_get(url, headers, params, timeout):
        page = int((params or {}).get("page") or parse_qs(urlparse(url).query)["page"][0])
        requested_pages.append(page)
        if page == 1:
            next_url = (
                "https://api.github.com/repos/acme/widgets/pulls/7/files"
                "?per_page=100&page=2"
            )
            return FakeResponse([_file(i) for i in range(100)], next_url=next_url)
        if page == 2:
            return FakeResponse([_file(i) for i in range(100, 200)])
        return FakeResponse([])

    monkeypatch.setattr(client.requests, "get", fake_get)
    snapshot = client.get_pr_files("acme/widgets", 7, "token")

    assert len(snapshot.files) == 200
    assert snapshot.limit_reached is False
    assert requested_pages == [1, 2, 3]


def test_check_runs_follow_links_and_permission_failure_is_unavailable(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append((url, params))
        if len(calls) == 1:
            return FakeResponse(
                {
                    "check_runs": [
                        {"id": index, "name": f"check-{index}"}
                        for index in range(100)
                    ]
                },
                next_url=(
                    "https://api.github.com/repos/acme/widgets/commits/"
                    "abc/check-runs?per_page=100&page=2"
                ),
            )
        return FakeResponse(
            {"check_runs": [{"id": 100, "name": "check-100"}]}
        )

    monkeypatch.setattr(client.requests, "get", fake_get)
    snapshot = client.get_check_runs("acme/widgets", "abc", "token")
    assert len(snapshot.check_runs) == 101
    assert snapshot.limit_reached is False
    assert calls[1][1] is None

    monkeypatch.setattr(
        client.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({}, status_code=403),
    )
    unavailable = client.get_check_runs("acme/widgets", "abc", "token")
    assert unavailable.check_runs == []
    assert "permission" in unavailable.error.lower()
