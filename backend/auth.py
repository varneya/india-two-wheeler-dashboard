"""
Opt-in admin guard for mutating / expensive endpoints.

ADMIN_TOKEN unset (default)  -> require_admin is a no-op, preserving the
local-first topology where every visitor runs their own backend and needs
no credentials.

ADMIN_TOKEN set (shared / public deployment) -> the guarded endpoints
demand a matching X-Admin-Token header; everything read-only stays open.
"""

import hmac

from fastapi import Header, HTTPException

from config import settings


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = settings.admin_token
    if not expected:
        return
    # Compare as bytes: compare_digest(str, str) raises TypeError on any
    # non-ASCII character (turning a bad token into a 500 instead of a 401).
    # surrogateescape survives whatever bytes the client smuggled into the
    # latin-1-decoded header value.
    supplied = (x_admin_token or "").encode("utf-8", "surrogateescape")
    if not x_admin_token or not hmac.compare_digest(supplied, expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="admin token required")
