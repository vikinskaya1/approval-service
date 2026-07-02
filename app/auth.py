"""Local auth stub.

Real deployments would sit behind a gateway/auth service that resolves a
token into (workspace_id, user_id, scopes). For local running and tests we
read that same triple straight from headers, so the downstream code has a
single `AuthContext` shape it can rely on regardless of how it was produced.

Expected headers on every request:
    X-User-Id:    opaque external user id, e.g. "usr_1"
    X-Workspace-Id: opaque external workspace id, e.g. "ws_1"
    X-Scopes:     comma-separated list of scopes, e.g. "approval:read,approval:create"

Scopes:
    approval:read    - list/get requests
    approval:create  - create a request
    approval:decide  - approve/reject a request
    approval:cancel  - cancel a request

The workspace_id in the URL path must match X-Workspace-Id. This is the
mechanism that keeps one workspace's data from ever being reachable through
another workspace's credentials.
"""
from dataclasses import dataclass

from fastapi import Header, HTTPException, Path, status


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    workspace_id: str
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope: {scope}",
            )


def get_auth_context(
    workspace_id: str = Path(...),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    x_scopes: str | None = Header(default=None, alias="X-Scopes"),
) -> AuthContext:
    if not x_user_id or not x_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-User-Id / X-Workspace-Id auth headers",
        )

    if x_workspace_id != workspace_id:
        # The caller's token is scoped to a different workspace than the one
        # in the URL. Treat this exactly like "not found" for the requested
        # workspace's data rather than leaking that it exists.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="auth context workspace does not match requested workspace",
        )

    scopes = frozenset(s.strip() for s in (x_scopes or "").split(",") if s.strip())
    return AuthContext(user_id=x_user_id, workspace_id=x_workspace_id, scopes=scopes)
