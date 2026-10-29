"""Operator authentication (the default auth mode): logins, roles, revocation, machine token limits."""
import pytest
from fastapi.testclient import TestClient

from app.auth import check_password, hash_password, sign, verify
from app.config import Settings
from app.main import create_app
from app.recovery.executors import MockExecutor
from tests.test_incidents import NOW, baseline, recent

MACHINE = {"Authorization": "Bearer machine-token"}
RC = "/api/v1/recovery-contracts"


@pytest.fixture()
def api(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'a.db'}", ingest_token="machine-token",
                        session_secret="s" * 40, bootstrap_admin="root:root-password-123", max_batch_events=2000)
    assert settings.auth_mode == "operators"  # the default
    return TestClient(create_app(settings, executor=MockExecutor()))


def login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def add(client, admin, username, role):
    r = client.post("/api/v1/operators", json={"username": username, "password": f"{username}-password-123", "role": role},
                    headers=admin)
    assert r.status_code == 201, r.text
    return login(client, username, f"{username}-password-123")


@pytest.fixture()
def team(api):
    admin = login(api, "root", "root-password-123")
    return api, admin, add(api, admin, "alice", "responder"), add(api, admin, "bob", "approver"), add(api, admin, "vera", "viewer")


def s01(client):
    r = client.post("/api/v1/telemetry/events?adapter=shop_json",
                    json={"events": baseline() + recent(500, 1, version="v2", message="unhandled_exception")}, headers=MACHINE)
    assert r.json()["rejected"] == 0
    [inc] = client.post("/api/v1/incidents/analyze", params={"as_of": NOW.isoformat()}, headers=MACHINE).json()
    return inc


def test_password_hashing_and_token_signing():
    h = hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert check_password("correct horse battery", h) and not check_password("wrong", h)
    t = sign("k" * 32, {"sub": "a", "exp": 9e9})
    assert verify("k" * 32, t)["sub"] == "a"
    assert verify("other-secret-key-xxxxxxxxxxxxxxx", t) is None
    assert verify("k" * 32, t[:-2] + "xx") is None
    assert verify("k" * 32, sign("k" * 32, {"sub": "a", "exp": 1})) is None  # expired


def test_login_and_me(team):
    client, _, alice, *_ = team
    me = client.get("/api/v1/auth/me", headers=alice).json()
    assert me == {"kind": "operator", "username": "alice", "role": "responder", "mode": "operators"}
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"}).status_code == 401


def test_identity_comes_from_the_session_not_from_x_actor(team):
    client, _, alice, bob, _ = team
    inc = s01(client)
    c = client.post(RC, json={"incident_id": inc["id"]}, headers={**alice, "X-Actor": "bob"}).json()
    assert c["proposed_by"] == "alice"  # the header is ignored
    # so alice cannot approve her own contract by claiming to be someone else
    assert client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers={**alice, "X-Actor": "bob"}).status_code == 403
    ok = client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=bob)
    assert ok.status_code == 200 and ok.json()["approvals"][0]["reviewer"] == "bob"


def test_roles_gate_actions(team):
    client, admin, alice, bob, vera = team
    inc = s01(client)
    assert client.get("/api/v1/incidents", headers=vera).status_code == 200  # viewers read
    assert client.post(RC, json={"incident_id": inc["id"]}, headers=vera).status_code == 403
    c = client.post(RC, json={"incident_id": inc["id"]}, headers=alice).json()
    res = client.post(f"{RC}/{c['id']}/approve", json={"decision": "approve"}, headers=alice)
    assert res.status_code == 403 and res.json()["detail"] == "role_approver_required"
    assert client.get("/api/v1/operators", headers=bob).status_code == 403
    assert client.get("/api/v1/operators", headers=admin).status_code == 200


def test_machine_token_can_ingest_and_analyse_but_never_act(team):
    client, *_ = team
    inc = s01(client)  # ingest + analyse with the machine token
    assert client.post(f"/api/v1/incidents/{inc['id']}/investigate", json={}, headers=MACHINE).status_code == 200
    for path, body in ((RC, {"incident_id": inc["id"]}), (f"/api/v1/incidents/{inc['id']}/label", {"label": "unknown"})):
        r = client.post(path, json=body, headers={**MACHINE, "X-Actor": "alice"})
        assert r.status_code == 403 and r.json()["detail"] == "operator_login_required"


def test_logout_revokes_existing_sessions(team):
    client, _, alice, *_ = team
    assert client.post("/api/v1/auth/logout", headers=alice).json() == {"logged_out": True}
    assert client.get("/api/v1/auth/me", headers=alice).status_code == 401
    again = login(client, "alice", "alice-password-123")
    assert client.get("/api/v1/auth/me", headers=again).status_code == 200


def test_disabling_an_operator_revokes_access_immediately(team):
    client, admin, alice, *_ = team
    r = client.patch("/api/v1/operators/alice", json={"disabled": True}, headers=admin)
    assert r.status_code == 200 and r.json()["disabled"] is True
    assert client.get("/api/v1/incidents", headers=alice).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-password-123"}).status_code == 401


def test_role_change_applies_to_existing_sessions(team):
    client, admin, alice, *_ = team
    client.patch("/api/v1/operators/alice", json={"role": "viewer"}, headers=admin)
    assert client.get("/api/v1/auth/me", headers=alice).json()["role"] == "viewer"


def test_admin_cannot_lock_themselves_out(team):
    client, admin, *_ = team
    assert client.patch("/api/v1/operators/root", json={"disabled": True}, headers=admin).status_code == 409
    assert client.patch("/api/v1/operators/root", json={"role": "viewer"}, headers=admin).status_code == 409


def test_password_change_logs_out_everywhere(team):
    client, _, alice, *_ = team
    r = client.post("/api/v1/auth/password", json={"current_password": "alice-password-123", "new_password": "a-new-password-456"},
                    headers=alice)
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=alice).status_code == 401
    login(client, "alice", "a-new-password-456")


def test_repeated_failures_lock_the_account(team):
    client, *_ = team
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-password-123"})
    assert r.status_code == 429


def test_weak_passwords_and_bad_usernames_are_rejected(team):
    client, admin, *_ = team
    assert client.post("/api/v1/operators", json={"username": "eve", "password": "short", "role": "viewer"}, headers=admin).status_code == 422
    assert client.post("/api/v1/operators", json={"username": "Bad Name", "password": "x" * 20, "role": "viewer"}, headers=admin).status_code == 422
    assert client.post("/api/v1/operators", json={"username": "eve", "password": "x" * 20, "role": "god"}, headers=admin).status_code == 422


def test_forged_and_missing_tokens_are_rejected(team):
    client, *_ = team
    forged = sign("not-the-server-secret-at-all-xxxxxx", {"sub": "root", "iat": 1, "exp": 9e9})
    assert client.get("/api/v1/incidents", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/api/v1/incidents").status_code == 401
    assert client.get("/api/v1/incidents", headers={"X-Actor": "root"}).status_code == 401


def test_without_a_session_secret_nobody_can_log_in(tmp_path):
    client = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'n.db'}", ingest_token="machine-token",
                                            bootstrap_admin="root:root-password-123")))
    assert client.post("/api/v1/auth/login", json={"username": "root", "password": "root-password-123"}).status_code == 503
    assert client.get("/api/v1/auth/mode").json() == {"mode": "operators", "login_configured": False}


def test_bootstrap_admin_is_only_used_while_no_operator_exists(tmp_path):
    url = f"sqlite:///{tmp_path / 'b.db'}"
    common = dict(database_url=url, ingest_token="m", session_secret="s" * 40)
    c1 = TestClient(create_app(Settings(**common, bootstrap_admin="root:root-password-123")))
    login(c1, "root", "root-password-123")
    c2 = TestClient(create_app(Settings(**common, bootstrap_admin="other:other-password-123")))
    assert c2.post("/api/v1/auth/login", json={"username": "other", "password": "other-password-123"}).status_code == 401


def test_session_expiry(tmp_path):
    client = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'e.db'}", ingest_token="m",
                                            session_secret="s" * 40, bootstrap_admin="root:root-password-123",
                                            session_ttl_seconds=-1)))
    headers = login(client, "root", "root-password-123")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_shared_token_mode_needs_the_development_flag(tmp_path):
    from app.auth import InsecureModeRefused, check_mode
    base = dict(database_url=f"sqlite:///{tmp_path / 'x.db'}", ingest_token="m", auth_mode="shared_token")
    with pytest.raises(InsecureModeRefused, match="ALLOW_INSECURE_SHARED_TOKEN"):
        create_app(Settings(**base))
    check_mode(Settings(**base, allow_insecure_shared_token=True), environ={})  # local development: allowed
    with pytest.raises(InsecureModeRefused, match="hosted"):
        check_mode(Settings(**base, allow_insecure_shared_token=True), environ={"RENDER": "true"})


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(ValueError):
        Settings(auth_mode="open")


def test_a_lockout_from_one_address_does_not_lock_the_operator_out_elsewhere(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'l.db'}", ingest_token="machine-token",
                              session_secret="s" * 40, bootstrap_admin="root:root-password-123"))
    attacker, owner = TestClient(app, client=("203.0.113.9", 4000)), TestClient(app, client=("198.51.100.7", 4000))
    for _ in range(5):
        assert attacker.post("/api/v1/auth/login", json={"username": "root", "password": "wrong"}).status_code == 401
    assert attacker.post("/api/v1/auth/login", json={"username": "root", "password": "root-password-123"}).status_code == 429
    assert owner.post("/api/v1/auth/login", json={"username": "root", "password": "root-password-123"}).status_code == 200


def test_a_non_ascii_token_is_a_401_not_a_server_error(api):
    res = api.get("/api/v1/incidents", headers={"Authorization": "Bearer tokén".encode("latin-1")})
    assert res.status_code == 401
