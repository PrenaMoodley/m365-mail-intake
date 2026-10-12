"""A small Microsoft Graph client: app-only OAuth, paging, delta queries, retries.

Uses the OAuth 2.0 client credentials flow against Microsoft Entra ID, so it runs
unattended as a service with no user signed in. Permissions are application
permissions scoped down to one mailbox and one SharePoint site; see docs/PERMISSIONS.md.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SMALL_UPLOAD_LIMIT = 4 * 1024 * 1024  # simple PUT upload is for files up to 4 MB


@dataclass(frozen=True)
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str


class GraphError(RuntimeError):
    pass


class Graph:
    def __init__(self, config: GraphConfig, http: httpx.Client | None = None, sleep=time.sleep):
        self.config = config
        self.http = http or httpx.Client(timeout=30)
        self.sleep = sleep
        self._token: str | None = None
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = self.http.post(
            f"{LOGIN}/{self.config.tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        if r.status_code != 200:
            raise GraphError(f"Token request failed: {r.status_code} {r.text}")
        body = r.json()
        self._token, self._expires = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if url.startswith("/"):
            url = GRAPH + url
        extra_headers = kwargs.pop("headers", {})
        for attempt in range(5):
            headers = {"Authorization": f"Bearer {self._access_token()}", **extra_headers}
            r = self.http.request(method, url, headers=headers, **kwargs)
            # Graph throttles with 429 (and sometimes 503) and says how long to wait.
            if r.status_code in (429, 503, 504):
                self.sleep(int(r.headers.get("Retry-After", 2**attempt)))
                continue
            if r.status_code >= 400:
                raise GraphError(f"{method} {url}: {r.status_code} {r.text[:300]}")
            return r
        raise GraphError(f"{method} {url}: still throttled after retries")

    # ------------------------------------------------------------- mail

    def message_delta(self, mailbox: str, folder: str, delta_link: str | None) -> tuple[list[dict], str]:
        """New or changed messages since the last run. Returns (messages, next delta link).

        The first run (no delta link) returns the folder's current messages; each
        later run returns only what changed, which is far cheaper than re-listing.
        """
        url = delta_link or (
            f"/users/{quote(mailbox)}/mailFolders/{quote(folder)}/messages/delta"
            "?$select=id,subject,from,receivedDateTime,hasAttachments"
        )
        messages: list[dict] = []
        while True:
            body = self.request("GET", url).json()
            messages += [m for m in body.get("value", []) if "@removed" not in m]
            if "@odata.nextLink" in body:
                url = body["@odata.nextLink"]
            else:
                return messages, body["@odata.deltaLink"]

    def file_attachments(self, mailbox: str, message_id: str) -> Iterator[tuple[str, str, bytes]]:
        """(name, content type, bytes) for each real file attachment; inline images are skipped."""
        url = f"/users/{quote(mailbox)}/messages/{message_id}/attachments"
        for a in self.request("GET", url).json()["value"]:
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment" or a.get("isInline"):
                continue
            yield a["name"], a.get("contentType") or "", base64.b64decode(a["contentBytes"])

    def move_message(self, mailbox: str, message_id: str, destination_folder_id: str) -> None:
        self.request(
            "POST",
            f"/users/{quote(mailbox)}/messages/{message_id}/move",
            json={"destinationId": destination_folder_id},
        )

    # ------------------------------------------------------------- SharePoint / OneDrive

    def upload_small_file(self, drive_id: str, path: str, content: bytes) -> dict:
        if len(content) > SMALL_UPLOAD_LIMIT:
            raise GraphError(f"{path} is over 4 MB; use an upload session for large files")
        r = self.request(
            "PUT",
            f"/drives/{drive_id}/root:/{quote(path)}:/content",
            # Two different invoices with the same file name on the same day are kept
            # side by side; identical files never get this far (hash check in intake.py).
            params={"@microsoft.graph.conflictBehavior": "rename"},
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return r.json()

    # ------------------------------------------------------------- change notifications

    def subscribe_to_new_mail(
        self, mailbox: str, folder: str, notification_url: str, client_state: str, expires_iso: str
    ) -> dict:
        """Ask Graph to POST to notification_url when mail arrives. Mail subscriptions
        expire within days, so a scheduled job must renew them (PATCH expirationDateTime)."""
        return self.request(
            "POST",
            "/subscriptions",
            json={
                "changeType": "created",
                "notificationUrl": notification_url,
                "resource": f"users/{mailbox}/mailFolders('{folder}')/messages",
                "expirationDateTime": expires_iso,
                "clientState": client_state,
            },
        ).json()
