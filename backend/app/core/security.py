from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Sequence, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    """Unified authenticated principal resolved from the shared HS256 JWT."""

    id: str
    sub: str
    email: str
    role: UserRole
    external_crm_agent_id: Optional[str] = None
    manager_id: Optional[str] = None
    full_name: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt (cost factor 12)."""
    return pwd_context.hash(password, rounds=12)


def create_access_token(
    data: Optional[Dict[str, Any]] = None,
    *,
    sub: Optional[Union[str, uuid.UUID]] = None,
    email: Optional[str] = None,
    role: Optional[Union[UserRole, str]] = None,
    external_crm_agent_id: Optional[str] = None,
    manager_id: Optional[Union[str, uuid.UUID]] = None,
    expires_delta: Optional[timedelta] = None,
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> str:
    """
    Create a standard HS256-signed JWT matching the Auth.js v5 cross-service contract.
    Supports passing a `data` dictionary, explicit keyword arguments, or both.
    """
    payload: Dict[str, Any] = dict(data) if data else {}

    if sub is not None:
        payload["sub"] = str(sub)
    elif "sub" in payload and payload["sub"] is not None:
        payload["sub"] = str(payload["sub"])

    if email is not None:
        payload["email"] = email

    if role is not None:
        payload["role"] = role.value if isinstance(role, UserRole) else str(role)
    elif "role" in payload and isinstance(payload["role"], UserRole):
        payload["role"] = payload["role"].value

    if external_crm_agent_id is not None or "external_crm_agent_id" not in payload:
        payload["external_crm_agent_id"] = external_crm_agent_id

    if manager_id is not None:
        payload["manager_id"] = str(manager_id)
    elif "manager_id" in payload and payload["manager_id"] is not None:
        payload["manager_id"] = str(payload["manager_id"])
    else:
        payload.setdefault("manager_id", None)

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int(expire.timestamp())

    signing_key = secret_key if secret_key is not None else settings.AUTH_SECRET
    signing_alg = algorithm if algorithm is not None else settings.JWT_ALGORITHM

    return jwt.encode(payload, signing_key, algorithm=signing_alg)


def decode_access_token(token: str) -> AuthenticatedUser:
    """
    Verify and decode an HS256 JWT token signed with the shared `AUTH_SECRET`.
    Raises 401 Unauthorized if the signature, expiration, or payload claims are invalid.
    """
    unauthorized_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise unauthorized_exc from exc

    sub = payload.get("sub") or payload.get("id")
    email = payload.get("email")
    raw_role = payload.get("role")

    if not sub or not email or not raw_role:
        raise unauthorized_exc

    try:
        role = UserRole(str(raw_role))
    except ValueError as exc:
        raise unauthorized_exc from exc

    external_crm_agent_id = payload.get("external_crm_agent_id")
    manager_id = payload.get("manager_id")

    return AuthenticatedUser(
        id=str(sub),
        sub=str(sub),
        email=str(email),
        role=role,
        external_crm_agent_id=str(external_crm_agent_id) if external_crm_agent_id else None,
        manager_id=str(manager_id) if manager_id else None,
        full_name=payload.get("name") or payload.get("full_name"),
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """
    FastAPI dependency that extracts and verifies the Bearer HS256 JWT token.
    Returns 401 Unauthorized if missing, malformed, expired, or belonging to an inactive user.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_claims = decode_access_token(credentials.credentials)

    try:
        user_uuid = uuid.UUID(user_claims.sub)
        stmt = select(User).where(User.id == user_uuid)
        result = await db.execute(stmt)
        db_user = result.scalar_one_or_none()
        if db_user is not None:
            if not db_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is inactive",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user_claims.full_name = db_user.full_name
            user_claims.external_crm_agent_id = db_user.external_crm_agent_id
            user_claims.manager_id = str(db_user.manager_id) if db_user.manager_id else None
    except ValueError:
        pass

    return user_claims


def require_roles(*allowed_roles: Union[UserRole, str]) -> Callable[..., Any]:
    """
    FastAPI RBAC dependency factory enforcing that the authenticated user holds one of `allowed_roles`.
    Returns 401 Unauthorized for missing/invalid tokens and 403 Forbidden for insufficient role permissions.
    """
    normalized_roles: Sequence[UserRole] = [
        role if isinstance(role, UserRole) else UserRole(str(role))
        for role in allowed_roles
    ]

    async def role_checker(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if current_user.role not in normalized_roles:
            allowed_names = ", ".join(r.value for r in normalized_roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions: role '{current_user.role.value}' "
                    f"is not permitted. Required one of: [{allowed_names}]"
                ),
            )
        return current_user

    return role_checker

