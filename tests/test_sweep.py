import pytest
import requests
from sweep import (
    fetch_inventory_pages,
    fetch_with_retry,
    parse_as_of,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}"
            )


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            }
        )

        if not self.responses:
            raise AssertionError(
                "FakeSession has no more responses"
            )

        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


def test_parse_utc_timestamp():
    dt = parse_as_of(
        "2026-09-28T04:30:00Z"
    )

    assert dt.isoformat() == (
        "2026-09-28T04:30:00+00:00"
    )


def test_parse_offset_timestamp():
    dt = parse_as_of(
        "2026-09-28T10:00:00+05:30"
    )

    assert dt.isoformat() == (
        "2026-09-28T04:30:00+00:00"
    )


def test_timezone_is_required():
    try:
        parse_as_of(
            "2026-09-28T04:30:00"
        )
    except ValueError as exc:
        assert "timezone" in str(exc)
    else:
        raise AssertionError(
            "Expected timezone validation error"
        )


def test_inventory_pages_are_deduplicated():
    """
    The API can repeat a SKU on another page.

    The scraper must keep only one observation per SKU.
    """

    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "items": [
                        {
                            "sku_id": "SKU-001",
                            "name": "Milk",
                            "in_stock": True,
                            "qty": 5,
                            "price": 20,
                            "observed_at": "2026-09-28T04:35:00Z",
                        },
                        {
                            "sku_id": "SKU-002",
                            "name": "Bread",
                            "in_stock": False,
                            "qty": 0,
                            "price": 30,
                            "observed_at": "2026-09-28T04:35:00Z",
                        },
                    ],
                    "next_cursor": "15",
                    "partial": False,
                    "meta": {"source": "origin"},
                },
            ),
            FakeResponse(
                200,
                {
                    "items": [
                        {
                            # Duplicate SKU from page 1.
                            "sku_id": "SKU-002",
                            "name": "Bread",
                            "in_stock": False,
                            "qty": 0,
                            "price": 30,
                            "observed_at": "2026-09-28T04:35:00Z",
                        },
                        {
                            "sku_id": "SKU-003",
                            "name": "Rice",
                            "in_stock": True,
                            "qty": 10,
                            "price": 50,
                            "observed_at": "2026-09-28T04:35:00Z",
                        },
                    ],
                    "next_cursor": None,
                    "partial": False,
                    "meta": {"source": "origin"},
                },
            ),
        ]
    )

    status, items, reason = fetch_inventory_pages(
        session,
        "MUM-001",
        parse_as_of("2026-09-28T04:30:00Z"),
    )

    assert status == "complete"
    assert reason is None

    sku_ids = [item["sku_id"] for item in items]

    assert len(items) == 3
    assert sorted(sku_ids) == [
        "SKU-001",
        "SKU-002",
        "SKU-003",
    ]

    # Two pages should have been requested.
    assert len(session.calls) == 2

    # The second request must use the cursor returned
    # by the first page.
    assert session.calls[1]["params"]["cursor"] == "15"


def test_partial_inventory_is_incomplete():
    """
    A response with partial=true must never be treated
    as a complete inventory snapshot.
    """

    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "items": [
                        {
                            "sku_id": "SKU-001",
                            "name": "Milk",
                            "in_stock": True,
                            "qty": 5,
                            "price": 20,
                            "observed_at": "2026-09-28T04:35:00Z",
                        }
                    ],
                    "next_cursor": None,
                    "partial": True,
                    "meta": {"source": "origin"},
                },
            )
        ]
    )

    status, items, reason = fetch_inventory_pages(
        session,
        "DEL-004",
        parse_as_of("2026-09-28T10:30:00Z"),
    )

    assert status == "incomplete"
    assert reason == "portal returned partial snapshot"


def test_soft_ban_is_detected():
    """
    HTTP 200 does not automatically mean the response is valid.

    meta.source=edge indicates the mock portal's soft-ban
    degraded response.
    """

    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "items": [],
                    "next_cursor": None,
                    "partial": False,
                    "meta": {"source": "edge"},
                },
            ),
            FakeResponse(
                200,
                {
                    "items": [],
                    "next_cursor": None,
                    "partial": False,
                    "meta": {"source": "edge"},
                },
            ),
            FakeResponse(
                200,
                {
                    "items": [],
                    "next_cursor": None,
                    "partial": False,
                    "meta": {"source": "edge"},
                },
            ),
            FakeResponse(
                200,
                {
                    "items": [],
                    "next_cursor": None,
                    "partial": False,
                    "meta": {"source": "edge"},
                },
            ),
        ]
    )

    status, items, reason = fetch_inventory_pages(
        session,
        "MUM-001",
        parse_as_of("2026-09-28T04:30:00Z"),
    )

    assert status == "incomplete"
    assert reason == "soft ban persisted after retries"
    assert items == []


def test_retry_after_is_respected(monkeypatch):
    """
    HTTP 429 should cause the scraper to wait for Retry-After
    instead of immediately hammering the server again.
    """

    sleep_calls = []

    monkeypatch.setattr(
        "sweep.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    session = FakeSession(
        [
            FakeResponse(
                429,
                headers={"Retry-After": "2"},
            ),
            FakeResponse(
                200,
                {
                    "ok": True,
                },
            ),
        ]
    )

    response = fetch_with_retry(
        session,
        "http://127.0.0.1:8765/v1/test",
        {},
    )

    assert response.status_code == 200
    assert 2.0 in sleep_calls


def test_503_is_retried(monkeypatch):
    """
    HTTP 503 is a transient server error.

    The scraper should retry instead of immediately failing.
    """

    sleep_calls = []

    monkeypatch.setattr(
        "sweep.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    session = FakeSession(
        [
            FakeResponse(503),
            FakeResponse(
                200,
                {
                    "ok": True,
                },
            ),
        ]
    )

    response = fetch_with_retry(
        session,
        "http://127.0.0.1:8765/v1/test",
        {},
    )

    assert response.status_code == 200
    assert len(session.calls) == 2
    assert sleep_calls


def test_timeout_is_retried(monkeypatch):
    """
    A timeout should not immediately kill the sweep.
    """

    sleep_calls = []

    monkeypatch.setattr(
        "sweep.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    session = FakeSession(
        [
            requests.Timeout("request timed out"),
            FakeResponse(
                200,
                {
                    "ok": True,
                },
            ),
        ]
    )

    response = fetch_with_retry(
        session,
        "http://127.0.0.1:8765/v1/test",
        {},
    )

    assert response.status_code == 200
    assert len(session.calls) == 2
    assert sleep_calls


def test_permanent_http_error_is_not_retried(monkeypatch):
    """
    Permanent HTTP errors such as 400 should fail immediately.

    They should not be retried because repeating the same invalid
    request will not normally fix the problem.
    """

    sleep_calls = []

    monkeypatch.setattr(
        "sweep.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    session = FakeSession(
        [
            FakeResponse(400),
        ]
    )

    with pytest.raises(requests.HTTPError):
        fetch_with_retry(
            session,
            "http://127.0.0.1:8765/v1/test",
            {},
        )

    # Only one request should have been made.
    assert len(session.calls) == 1

    # There should be no retry delay.
    assert sleep_calls == []