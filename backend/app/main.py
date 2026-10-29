from __future__ import annotations

from typing import Any, Dict

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.integrations import router as integrations_router
from app.api.v1.webhooks import router as webhooks_router
from app.core.config import settings
from app.core.security import AuthenticatedUser, get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import UserRole

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(integrations_router)


@app.get("/healthz", tags=["Health"])
async def healthcheck(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """
    Verify live connectivity to PostgreSQL (`SELECT 1`) and Redis (`PING`).
    """
    pg_status = "unhealthy"
    redis_status = "unhealthy"
    errors: Dict[str, str] = {}

    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            pg_status = "healthy"
    except Exception as exc:
        errors["postgres"] = str(exc)

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        pong = await redis_client.ping()
        if pong is True:
            redis_status = "healthy"
    except Exception as exc:
        errors["redis"] = str(exc)
    finally:
        await redis_client.aclose()

    is_healthy = pg_status == "healthy" and redis_status == "healthy"
    http_status = (
        status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    payload: Dict[str, Any] = {
        "status": "ok" if is_healthy else "degraded",
        "postgres": pg_status,
        "redis": redis_status,
        "services": {
            "postgres": pg_status,
            "redis": redis_status,
        },
    }
    if errors:
        payload["errors"] = errors

    return JSONResponse(status_code=http_status, content=payload)


@app.get("/api/v1/auth/me", tags=["Authentication"])
async def read_authenticated_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Return the currently authenticated user's profile and RBAC role decoded from the shared HS256 JWT.
    """
    return {
        "id": current_user.id,
        "sub": current_user.sub,
        "email": current_user.email,
        "role": current_user.role.value,
        "full_name": current_user.full_name,
        "external_crm_agent_id": current_user.external_crm_agent_id,
        "manager_id": current_user.manager_id,
    }


@app.get("/api/v1/manager/rbac-check", tags=["Manager RBAC"])
async def manager_rbac_check(
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.MANAGER, UserRole.ADMIN)
    ),
) -> Dict[str, Any]:
    """
    Protected verification endpoint accessible strictly to `MANAGER` and `ADMIN` roles.
    """
    return {
        "status": "authorized",
        "message": "Manager/Admin RBAC verification passed.",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "role": current_user.role.value,
        },
    }
