import uuid

from tests.conftest import auth_headers


def _create_payload(**overrides):
    payload = {
        "sourceType": "publication",
        "sourceId": "pub_123",
        "title": "Instagram reel draft",
        "description": "Needs final approval",
        "reviewerUserIds": ["usr_1", "usr_2"],
    }
    payload.update(overrides)
    return payload


def _idem_key():
    return str(uuid.uuid4())


def _create(client, workspace_id="ws_1", **overrides):
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/approval-requests",
        json=_create_payload(**overrides),
        headers={**auth_headers(workspace_id=workspace_id), "Idempotency-Key": _idem_key()},
    )


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_ready(self, client):
        r = client.get("/ready")
        assert r.status_code == 200


class TestAuth:
    def test_missing_headers_401(self, client):
        r = client.post(
            "/api/v1/workspaces/ws_1/approval-requests",
            json=_create_payload(),
            headers={"Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 401

    def test_workspace_mismatch_403(self, client):
        headers = {**auth_headers(workspace_id="ws_1"), "Idempotency-Key": _idem_key()}
        r = client.post("/api/v1/workspaces/ws_2/approval-requests", json=_create_payload(), headers=headers)
        assert r.status_code == 403

    def test_missing_scope_403(self, client):
        headers = {
            **auth_headers(workspace_id="ws_1", scopes=["approval:read"]),
            "Idempotency-Key": _idem_key(),
        }
        r = client.post("/api/v1/workspaces/ws_1/approval-requests", json=_create_payload(), headers=headers)
        assert r.status_code == 403

    def test_missing_idempotency_key_400(self, client):
        r = client.post(
            "/api/v1/workspaces/ws_1/approval-requests",
            json=_create_payload(),
            headers=auth_headers(workspace_id="ws_1"),
        )
        assert r.status_code == 400


class TestCreate:
    def test_create_success(self, client):
        r = _create(client)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending"
        assert body["sourceType"] == "publication"
        assert body["sourceId"] == "pub_123"
        assert body["reviewerUserIds"] == ["usr_1", "usr_2"]
        assert body["createdBy"] == "usr_1"
        assert body["decidedBy"] is None

    def test_create_invalid_source_type_422(self, client):
        r = _create(client, sourceType="not_a_real_type")
        assert r.status_code == 422

    def test_create_missing_title_422(self, client):
        r = client.post(
            "/api/v1/workspaces/ws_1/approval-requests",
            json={"sourceType": "publication", "sourceId": "pub_1", "title": ""},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 422


class TestIdempotency:
    def test_replayed_request_returns_same_result_no_duplicate(self, client):
        key = _idem_key()
        headers = {**auth_headers(), "Idempotency-Key": key}
        payload = _create_payload()

        r1 = client.post("/api/v1/workspaces/ws_1/approval-requests", json=payload, headers=headers)
        r2 = client.post("/api/v1/workspaces/ws_1/approval-requests", json=payload, headers=headers)

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

        listing = client.get("/api/v1/workspaces/ws_1/approval-requests", headers=auth_headers())
        assert listing.json()["total"] == 1

    def test_same_key_different_payload_conflict(self, client):
        key = _idem_key()
        headers = {**auth_headers(), "Idempotency-Key": key}

        r1 = client.post(
            "/api/v1/workspaces/ws_1/approval-requests", json=_create_payload(), headers=headers
        )
        r2 = client.post(
            "/api/v1/workspaces/ws_1/approval-requests",
            json=_create_payload(title="A different title"),
            headers=headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 409


class TestGetAndList:
    def test_get_404_for_unknown_id(self, client):
        r = client.get("/api/v1/workspaces/ws_1/approval-requests/does-not-exist", headers=auth_headers())
        assert r.status_code == 404

    def test_get_success(self, client):
        created = _create(client).json()
        r = client.get(f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}", headers=auth_headers())
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_list_filters_by_status(self, client):
        a = _create(client).json()
        _create(client, sourceId="pub_456")

        client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{a['id']}/approve",
            json={"comment": "Approved"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )

        r = client.get(
            "/api/v1/workspaces/ws_1/approval-requests", params={"status": "pending"}, headers=auth_headers()
        )
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["sourceId"] == "pub_456"

    def test_pagination(self, client):
        for i in range(5):
            _create(client, sourceId=f"pub_{i}")

        r = client.get(
            "/api/v1/workspaces/ws_1/approval-requests",
            params={"limit": 2, "offset": 0},
            headers=auth_headers(),
        )
        body = r.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2


class TestWorkspaceIsolation:
    def test_request_not_visible_from_other_workspace(self, client):
        created = _create(client, workspace_id="ws_1").json()

        r = client.get(
            f"/api/v1/workspaces/ws_2/approval-requests/{created['id']}",
            headers=auth_headers(workspace_id="ws_2"),
        )
        assert r.status_code == 404

        listing = client.get("/api/v1/workspaces/ws_2/approval-requests", headers=auth_headers(workspace_id="ws_2"))
        assert listing.json()["total"] == 0


class TestDecisions:
    def test_approve_success(self, client):
        created = _create(client).json()
        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/approve",
            json={"comment": "Looks good"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["decisionComment"] == "Looks good"
        assert body["decidedBy"] == "usr_1"
        assert body["decidedAt"] is not None

    def test_reject_requires_reason(self, client):
        created = _create(client).json()
        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/reject",
            json={},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 422

    def test_reject_success(self, client):
        created = _create(client).json()
        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/reject",
            json={"reason": "Brand tone is wrong"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"
        assert r.json()["decisionReason"] == "Brand tone is wrong"

    def test_cancel_success(self, client):
        created = _create(client).json()
        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/cancel",
            json={"reason": "Draft was removed"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_cannot_transition_after_final_state(self, client):
        created = _create(client).json()
        client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/approve",
            json={"comment": "Approved"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )

        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/reject",
            json={"reason": "Changed my mind"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 409

    def test_decide_missing_scope_403(self, client):
        created = _create(client).json()
        r = client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/approve",
            json={"comment": "Approved"},
            headers={
                **auth_headers(scopes=["approval:read", "approval:create"]),
                "Idempotency-Key": _idem_key(),
            },
        )
        assert r.status_code == 403

    def test_approve_unknown_id_404(self, client):
        r = client.post(
            "/api/v1/workspaces/ws_1/approval-requests/does-not-exist/approve",
            json={"comment": "Approved"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )
        assert r.status_code == 404


class TestAuditAndEvents:
    def test_audit_log_and_outbox_event_written(self, client, db_session):
        created = _create(client).json()
        client.post(
            f"/api/v1/workspaces/ws_1/approval-requests/{created['id']}/approve",
            json={"comment": "Approved"},
            headers={**auth_headers(), "Idempotency-Key": _idem_key()},
        )

        from app.models import AuditLog, OutboxEvent

        session = db_session()
        try:
            logs = session.query(AuditLog).filter_by(approval_request_id=created["id"]).all()
            actions = sorted(log.action for log in logs)
            assert actions == ["approved", "created"]
            assert all(log.actor_user_id == "usr_1" for log in logs)

            events = session.query(OutboxEvent).filter_by(approval_request_id=created["id"]).all()
            event_types = sorted(e.event_type for e in events)
            assert event_types == ["approval_request.approved", "approval_request.created"]
        finally:
            session.close()
