import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from fairy.autonomy import AutonomyService
from fairy.worker import dispatch_due_reminders, run_cycle
from fairy.store import now
from tests.db import postgres_url


@pytest.fixture
def env(tmp_path):
    app = create_app(postgres_url(tmp_path), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def make_card(client, subtype, remind_at, key):
    return client.post(
        "/v2/cards",
        json={"title": "喝水", "text": "起来喝水", "subtype": subtype, "remind_at": remind_at},
        headers={"Idempotency-Key": key},
    ).json()


def reminder_events(client):
    return [e for e in client.get("/v2/events").json() if e["type"] == "card.reminder_due"]


def test_due_reminder_fires_once_and_is_flagged(env):
    app, client = env
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    card = make_card(client, "reminder", past, "c1")
    fired = dispatch_due_reminders(app.state.db)
    assert fired == [card["id"]]
    events = reminder_events(client)
    assert len(events) == 1
    assert events[0]["payload"]["title"] == "喝水"
    assert events[0]["payload"]["id"] == card["id"]
    stored = next(c for c in client.get("/v2/cards").json() if c["id"] == card["id"])
    assert stored["reminded_at"]
    assert dispatch_due_reminders(app.state.db) == []
    assert len(reminder_events(client)) == 1


def test_future_and_non_reminder_cards_do_not_fire(env):
    app, client = env
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    make_card(client, "reminder", future, "f1")
    make_card(client, "note", past, "n1")
    make_card(client, "todo", past, "t1")
    assert dispatch_due_reminders(app.state.db) == []
    assert reminder_events(client) == []


def test_anniversary_due_fires(env):
    app, client = env
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    card = make_card(client, "anniversary", past, "a1")
    assert dispatch_due_reminders(app.state.db) == [card["id"]]


def test_reminders_dispatch_even_when_study_paused(env, tmp_path):
    app, client = env
    assert client.put("/v2/config", json={"revision": 0, "daily_minutes": 0}).status_code == 200
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    make_card(client, "reminder", past, "p1")
    state = tmp_path / "worker-state"
    state.mkdir()
    healthy = run_cycle(app.state.db, AutonomyService(app.state.db), str(state), now(), 1)
    assert healthy is True
    from fairy.worker import read_status
    status = read_status(str(state))
    assert status["tick_processed"] is False
    assert status["reminders_dispatched"] == 1
    assert len(reminder_events(client)) == 1
