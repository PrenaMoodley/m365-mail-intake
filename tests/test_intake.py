import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mail_intake.graph import Graph, GraphConfig, GraphError
from mail_intake.intake import IntakeConfig, State, run, safe_name, target_path
from mail_intake.webhook import create_app

PDF = b"%PDF-1.7 fake invoice"
CFG = IntakeConfig(mailbox="invoices@example.co.za", folder="inbox", filed_folder_id="FILED", drive_id="D1")


def attachment(name, content, content_type="application/pdf", inline=False, kind="fileAttachment"):
    return {
        "@odata.type": f"#microsoft.graph.{kind}",
        "name": name,
        "contentType": content_type,
        "isInline": inline,
        "contentBytes": base64.b64encode(content).decode(),
    }


class FakeGraph:
    """A minimal fake Microsoft Graph tenant behind httpx.MockTransport."""

    def __init__(self, messages, attachments):
        self.messages, self.attachments = messages, attachments
        self.uploads, self.moved, self.calls = {}, [], []
        self.throttle_next = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        if "oauth2/v2.0/token" in url:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        if self.throttle_next:
            self.throttle_next -= 1
            return httpx.Response(429, headers={"Retry-After": "1"})
        if "/messages/delta" in url and "page2" not in url and "deltatoken" not in url:
            return httpx.Response(200, json={"value": self.messages[:1], "@odata.nextLink": url + "&page2=1"})
        if "page2" in url:
            return httpx.Response(
                200,
                json={"value": self.messages[1:], "@odata.deltaLink": "https://graph/delta?deltatoken=abc"},
            )
        if "deltatoken" in url:
            return httpx.Response(200, json={"value": [], "@odata.deltaLink": url})
        if url.endswith("/attachments"):
            msg_id = url.split("/messages/")[1].split("/")[0]
            return httpx.Response(200, json={"value": self.attachments.get(msg_id, [])})
        if request.method == "PUT" and "/content" in url:
            assert "conflictBehavior=rename" in url
            self.uploads[url.split("root:/")[1].split(":/content")[0]] = request.content
            return httpx.Response(201, json={"id": "item"})
        if url.endswith("/move"):
            self.moved.append((url.split("/messages/")[1].split("/")[0], json.loads(request.content)))
            return httpx.Response(201, json={})
        return httpx.Response(404, text="not found")

    def client(self):
        return Graph(
            GraphConfig("t", "c", "s"),
            http=httpx.Client(transport=httpx.MockTransport(self.handler)),
            sleep=lambda s: None,
        )


def message(id, sender="accounts@supplier.co.za", subject="Invoice", attachments=True):
    return {
        "id": id,
        "subject": subject,
        "hasAttachments": attachments,
        "receivedDateTime": "2026-10-12T08:15:00Z",
        "from": {"emailAddress": {"address": sender}},
    }


def test_files_pdfs_skips_others_and_dedupes():
    fake = FakeGraph(
        [message("m1"), message("m2", sender="billing@other.com"), message("m3", attachments=False)],
        {
            "m1": [attachment("INV-001.pdf", PDF), attachment("logo.png", b"img", "image/png", inline=True)],
            "m2": [
                attachment("copy of INV-001.pdf", PDF),
                attachment("terms.docx", b"doc", "application/msword"),
            ],
        },
    )
    state = State()
    report = run(fake.client(), CFG, state)

    assert report.filed == ["Invoices/2026/10/supplier.co.za/2026-10-12_INV-001.pdf"]
    assert report.duplicates == ["copy of INV-001.pdf"]  # same bytes, different name
    assert report.skipped == ["terms.docx"]
    assert [m for m, _ in fake.moved] == ["m1", "m2"]
    assert fake.moved[0][1] == {"destinationId": "FILED"}
    assert state.delta_link.endswith("deltatoken=abc")


def test_next_run_uses_delta_link_and_finds_nothing_new():
    fake = FakeGraph([message("m1")], {"m1": [attachment("a.pdf", PDF)]})
    graph, state = fake.client(), State()
    run(graph, CFG, state)
    second = run(graph, CFG, state)
    assert second.messages == 0
    assert any("deltatoken=abc" in url for _, url in fake.calls[-2:])


def test_failure_keeps_message_and_does_not_advance_delta():
    fake = FakeGraph([message("m1")], {"m1": [attachment("a.pdf", PDF)]})
    original = fake.handler

    def failing(request):
        if request.method == "PUT":
            return httpx.Response(403, text="Access denied")
        return original(request)

    graph = Graph(GraphConfig("t", "c", "s"), http=httpx.Client(transport=httpx.MockTransport(failing)))
    state = State()
    report = run(graph, CFG, state)
    assert report.errors and "403" in report.errors[0]
    assert fake.moved == []
    assert state.delta_link is None  # the next run will see the message again


def test_throttling_is_retried():
    fake = FakeGraph([message("m1")], {"m1": [attachment("a.pdf", PDF)]})
    fake.throttle_next = 2
    assert run(fake.client(), CFG, State()).filed


def test_token_failure_is_clear():
    def handler(request):
        return httpx.Response(400, text="AADSTS7000215: Invalid client secret")

    graph = Graph(GraphConfig("t", "c", "bad"), http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(GraphError, match="Invalid client secret"):
        graph.request("GET", "/me")


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    State("link", {"h1", "h2"}).save(path)
    loaded = State.load(path)
    assert (loaded.delta_link, loaded.filed_hashes) == ("link", {"h1", "h2"})


def test_names_are_made_safe():
    assert safe_name('inv:01/"final".pdf') == "inv_01_final_.pdf"
    path = target_path(CFG, message("m", sender="Odd@Weird.Example"), "../../x.pdf")
    assert ".." not in path.split("/")
    assert path.startswith("Invoices/2026/10/weird.example/")


# ---------------------------------------------------------------- webhook


def test_webhook_validation_handshake():
    client = TestClient(create_app(lambda: None, client_state="secret"))
    r = client.post("/graph/notifications?validationToken=abc%20123")
    assert r.status_code == 200
    assert r.text == "abc 123"
    assert r.headers["content-type"].startswith("text/plain")


def test_webhook_runs_once_for_genuine_notifications_only():
    runs = []
    client = TestClient(create_app(lambda: runs.append(1), client_state="secret"))
    forged = {"value": [{"clientState": "guess", "resource": "x"}]}
    assert client.post("/graph/notifications", json=forged).status_code == 202
    assert runs == []
    genuine = {"value": [{"clientState": "secret"}, {"clientState": "secret"}]}
    assert client.post("/graph/notifications", json=genuine).status_code == 202
    assert runs == [1]
