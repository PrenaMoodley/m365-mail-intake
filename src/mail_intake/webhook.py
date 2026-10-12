"""Receiver for Microsoft Graph change notifications (new mail -> run intake now).

Graph's rules, which this follows:
- On subscription, Graph calls the URL with ?validationToken=...; reply 200 with
  the token as text/plain within 10 seconds, or the subscription is refused.
- Each notification carries the clientState we set; anything else is ignored.
- Reply 202 quickly and do the work afterwards; slow replies get throttled.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request, Response


def create_app(on_new_mail: Callable[[], object], client_state: str | None = None) -> FastAPI:
    app = FastAPI(title="Mail intake webhook")
    expected = client_state or os.environ.get("GRAPH_CLIENT_STATE", "")

    @app.post("/graph/notifications")
    async def notifications(request: Request, background: BackgroundTasks) -> Response:
        token = request.query_params.get("validationToken")
        if token is not None:
            return Response(content=token, media_type="text/plain", status_code=200)

        body = await request.json()
        genuine = [
            n
            for n in body.get("value", [])
            if expected and hmac.compare_digest(str(n.get("clientState", "")), expected)
        ]
        if genuine:
            # One run picks up every new message through the delta query, so a
            # burst of notifications only needs one run.
            background.add_task(on_new_mail)
        return Response(status_code=202)

    return app
