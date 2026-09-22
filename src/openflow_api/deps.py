from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from fastapi import Header, HTTPException, status
except ImportError:
    def Header(default: Any = None, *args: Any, **kwargs: Any) -> Any:  # type: ignore
        return default

    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class status:  # type: ignore
        HTTP_400_BAD_REQUEST = 400
        HTTP_401_UNAUTHORIZED = 401
        HTTP_404_NOT_FOUND = 404
        HTTP_201_CREATED = 201


@dataclass
class TenantContext:
    org_id: str
    project_id: str
    user_id: str = "anonymous"
    roles: list[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.roles is None:
            self.roles = ["member"]


def get_tenant_context(
    x_org_id: str | None = Header(None, alias="X-Org-Id"),
    x_project_id: str | None = Header(None, alias="X-Project-Id"),
    x_user_id: str | None = Header("default-user", alias="X-User-Id"),
) -> TenantContext:
    """Enforces tenant and project isolation on every API request (S3).
    
    Rejects requests missing organization or project context.
    """
    if not x_org_id or not str(x_org_id).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required tenant header: X-Org-Id",
        )
    if not x_project_id or not str(x_project_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required project header: X-Project-Id",
        )

    return TenantContext(
        org_id=str(x_org_id).strip(),
        project_id=str(x_project_id).strip(),
        user_id=(str(x_user_id) if x_user_id else "default-user").strip(),
    )

