"""Unattended release/rollback drill for the evolution ledger (no runtime changes)."""

import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from tests.db import postgres_url


@pytest.fixture
def env(tmp_path):
    app = create_app(postgres_url(tmp_path), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def experiment_body(name):
    return {
        "name": name,
        "baseline": "baseline",
        "cases": [
            {
                "input": "水的颜色",
                "required_terms": ["无色", "适用条件"],
                "forbidden_terms": ["保证"],
            }
        ],
        "candidates": [
            {"name": "baseline", "outputs": ["水通常无色。"]},
            {"name": "candidate", "outputs": ["水通常无色，并注明适用条件。"]},
        ],
    }


def make_approved(client, name, key):
    created = client.post(
        "/v2/evolution/experiments",
        json=experiment_body(name),
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    experiment = created.json()
    approved = client.post(
        f"/v2/evolution/experiments/{experiment['id']}/approve",
        json={"candidate": "candidate"},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def current(client):
    response = client.get("/v2/evolution/release")
    assert response.status_code == 200
    return response.json()


def test_unattended_release_rollback_drill(env):
    _, client = env
    assert current(client) is None

    first = make_approved(client, "实验一", "drill-1")
    released = client.post(f"/v2/evolution/experiments/{first['id']}/release")
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "released"
    assert released.json()["runtime_changed"] is False
    assert released.json()["scoring_immutable"] is True
    assert current(client)["id"] == first["id"]

    second = make_approved(client, "实验二", "drill-2")
    released2 = client.post(f"/v2/evolution/experiments/{second['id']}/release")
    assert released2.status_code == 200, released2.text
    assert current(client)["id"] == second["id"]
    superseded = next(
        item
        for item in client.get("/v2/evolution/experiments").json()
        if item["id"] == first["id"]
    )
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by"] == second["id"]

    rolled = client.post(f"/v2/evolution/experiments/{second['id']}/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "rolled_back"
    assert rolled.json()["runtime_changed"] is False
    restored = current(client)
    assert restored["id"] == first["id"]
    assert restored["restored_by"] == second["id"]

    rolled_first = client.post(f"/v2/evolution/experiments/{first['id']}/rollback")
    assert rolled_first.status_code == 200, rolled_first.text
    assert current(client) is None

    again = client.post(f"/v2/evolution/experiments/{first['id']}/rollback")
    assert again.status_code == 409
    assert again.json()["detail"] == "experiment_not_rollbackable"


def test_release_and_rollback_state_guards(env):
    _, client = env
    created = client.post(
        "/v2/evolution/experiments",
        json=experiment_body("守卫实验"),
        headers={"Idempotency-Key": "guard-1"},
    ).json()

    early = client.post(f"/v2/evolution/experiments/{created['id']}/release")
    assert early.status_code == 409
    assert early.json()["detail"] == "experiment_not_releasable"

    early_rollback = client.post(
        f"/v2/evolution/experiments/{created['id']}/rollback"
    )
    assert early_rollback.status_code == 409
    assert early_rollback.json()["detail"] == "experiment_not_rollbackable"

    approved = client.post(
        f"/v2/evolution/experiments/{created['id']}/approve",
        json={"candidate": "candidate"},
    ).json()
    rolled = client.post(
        f"/v2/evolution/experiments/{approved['id']}/rollback"
    ).json()
    assert rolled["status"] == "rolled_back"

    late_release = client.post(f"/v2/evolution/experiments/{created['id']}/release")
    assert late_release.status_code == 409
    late_approve = client.post(
        f"/v2/evolution/experiments/{created['id']}/approve",
        json={"candidate": "candidate"},
    )
    assert late_approve.status_code == 409
    assert current(client) is None
