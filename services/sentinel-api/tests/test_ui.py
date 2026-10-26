import re
from pathlib import Path

from tests.test_incidents import AUTH, baseline, client, recent, run  # noqa: F401
from tests.test_recovery import ALICE, RC, s01_incident

UI = Path(__file__).resolve().parent.parent / "app" / "ui"


def test_dashboard_is_served_with_a_strict_csp(client):
    for path in ("/ui/", "/ui/app.js", "/ui/style.css"):
        res = client.get(path)
        assert res.status_code == 200, path
        csp = res.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp
        assert res.headers["x-content-type-options"] == "nosniff" and res.headers["cache-control"] == "no-store"
    assert "<script src=\"/ui/app.js\">" in client.get("/ui/").text  # no inline script
    assert not re.search(r"<script>[^<]", client.get("/ui/").text)


def test_dashboard_script_never_uses_dangerous_dom_apis():
    """Telemetry text is untrusted: the page must build DOM with textContent only."""
    code = (UI / "app.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", code)  # comments may mention the names
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "srcdoc"):
        assert banned not in code, banned


def test_api_responses_are_not_given_ui_headers(client):
    assert "content-security-policy" not in client.get("/health").headers


def test_list_contracts_for_an_incident(client):
    inc = s01_incident(client)
    assert client.get(f"{RC}?incident_id={inc['id']}", headers=AUTH).json() == []
    made = client.post(RC, json={"incident_id": inc["id"]}, headers=ALICE).json()
    listed = client.get(f"{RC}?incident_id={inc['id']}", headers=AUTH).json()
    assert [c["id"] for c in listed] == [made["id"]] and listed[0]["state"] == "AWAITING_APPROVAL"
    assert client.get(f"{RC}?incident_id=other", headers=AUTH).json() == []
    assert client.get(f"{RC}?incident_id={inc['id']}").status_code == 401
