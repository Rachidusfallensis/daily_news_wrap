"""Tests for generic SSE broadcast helper (Slice A).

Verifies:
- broadcast_to_user sends to correct user's queues only (isolation)
- Dead (full) clients are pruned without raising
- broadcast_new_article delegates correctly

Run inside Docker:
    docker compose exec api pytest test_sse_broadcast.py -v
"""
import asyncio
import pytest

from sse import _sse_queues, broadcast_to_user, broadcast_new_article


@pytest.fixture(autouse=True)
def clear_queues():
    _sse_queues.clear()
    yield
    _sse_queues.clear()


def _add_client(user_id: int, client_id: str, maxsize: int = 10) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _sse_queues.setdefault(user_id, {})[client_id] = q
    return q


def test_broadcast_reaches_correct_user_only():
    q_a = _add_client(1, "c1")
    q_b = _add_client(2, "c2")

    asyncio.run(broadcast_to_user({"type": "ping"}, user_id=1))

    assert q_a.qsize() == 1
    assert q_b.qsize() == 0


def test_broadcast_reaches_all_connections_of_same_user():
    q1 = _add_client(1, "c1")
    q2 = _add_client(1, "c2")

    asyncio.run(broadcast_to_user({"type": "ping"}, user_id=1))

    assert q1.qsize() == 1
    assert q2.qsize() == 1


def test_broadcast_no_user_queued_is_noop():
    asyncio.run(broadcast_to_user({"type": "ping"}, user_id=99))


def test_dead_client_pruned_on_full_queue():
    q_full = _add_client(1, "dead", maxsize=1)
    q_full.put_nowait({"type": "old"})  # fill it up
    q_live = _add_client(1, "live")

    asyncio.run(broadcast_to_user({"type": "new"}, user_id=1))

    assert "dead" not in _sse_queues[1]
    assert q_live.qsize() == 1


def test_broadcast_new_article_wraps_correctly():
    q = _add_client(1, "c1")
    asyncio.run(broadcast_new_article({"id": 42, "title": "Test"}, user_id=1))

    msg = q.get_nowait()
    assert msg == {"type": "new_article", "data": {"id": 42, "title": "Test"}}


def test_message_contents_preserved():
    q = _add_client(1, "c1")
    payload = {"type": "discovery:done", "run_id": 7, "status": "done"}
    asyncio.run(broadcast_to_user(payload, user_id=1))

    received = q.get_nowait()
    assert received == payload


def test_user_a_does_not_receive_user_b_progress_event():
    q_a = _add_client(1, "c1")
    q_b = _add_client(2, "c2")

    asyncio.run(broadcast_to_user({"type": "discovery:expanding", "run_id": 5}, user_id=2))

    assert q_a.qsize() == 0
    assert q_b.qsize() == 1
