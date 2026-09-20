"""Read-only mode after the licence grace period (decision 1).

One ASGI middleware in front of every route: while ``licence_state.current().read_only``
(a release build whose licence expired more than ``GRACE_DAYS`` ago) any request that is
not a read and not on ``licence_state.READ_ONLY_ALLOWLIST`` is answered with 423 and

    {"detail": "The licence expired on <date>. Records are read-only until a renewed
     licence is installed.", "code": "licence_read_only"}

plus ``X-Error-Code: licence_read_only``. Sign-in, MFA enrolment, reads, exports and
installing a renewed licence keep working. The check is a cached file read and a date
comparison, so it costs nothing measurable per request.
"""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services import licence_state


def refusal(method: str, path: str) -> JSONResponse | None:
    """The 423 response for this request, or ``None`` when it may proceed."""
    if (method or "").upper() in licence_state.SAFE_METHODS:
        return None
    state = licence_state.current()
    if not state.read_only or licence_state.write_allowed(method, path):
        return None
    return JSONResponse(
        {"detail": licence_state.read_only_detail(state.expires), "code": licence_state.READ_ONLY_CODE},
        status_code=licence_state.READ_ONLY_STATUS,
        headers={"X-Error-Code": licence_state.READ_ONLY_CODE},
    )


class LicenceReadOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            response = refusal(scope.get("method", "GET"), scope.get("path", ""))
            if response is not None:
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
