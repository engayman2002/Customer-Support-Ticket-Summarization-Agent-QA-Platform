from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.webhooks import cache_integration_config
from app.core.crypto import encrypt_secret
from app.core.security import AuthenticatedUser, require_roles
from app.db.session import get_db
from app.models.enums import CrmType, UserRole
from app.models.integration import Integration
from app.services.ingestion_service import reconcile_integration_closed_tickets

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])


class IntegrationCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    crm_type: CrmType
    subdomain_or_base_url: str = Field(..., min_length=3, max_length=255)
    api_key: str = Field(..., min_length=1)
    webhook_secret: str = Field(..., min_length=1)
    config_metadata: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class IntegrationSyncRequest(BaseModel):
    since_timestamp: Optional[datetime] = None
    tickets: Optional[List[Dict[str, Any]]] = None


def _serialize_integration(integration: Integration) -> Dict[str, Any]:
    return {
        "id": str(integration.id),
        "name": integration.name,
        "crm_type": integration.crm_type.value,
        "subdomain_or_base_url": integration.subdomain_or_base_url,
        "config_metadata": integration.config_metadata,
        "is_active": integration.is_active,
        "webhook_url": f"/api/v1/webhooks/{integration.crm_type.value.lower()}/{integration.id}",
        "last_successful_sync_at": (
            integration.last_successful_sync_at.replace(
                tzinfo=timezone.utc
            ).isoformat()
            if integration.last_successful_sync_at
            else None
        ),
        "created_at": integration.created_at.replace(
            tzinfo=timezone.utc
        ).isoformat(),
    }


@router.get("")
async def list_integrations(
    _current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List all registered CRM integrations without exposing encrypted secrets."""
    stmt = select(Integration).order_by(Integration.created_at.desc())
    result = await db.execute(stmt)
    integrations = list(result.scalars().all())
    return {
        "data": [_serialize_integration(item) for item in integrations],
        "total": len(integrations),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_integration(
    payload: IntegrationCreateRequest,
    _current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Register a new CRM integration (`ADMIN` only), encrypting `api_key` and
    `webhook_secret` at rest using AES-256-GCM (`enc_aes256gcm_v1:...`).
    """
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    integration = Integration(
        id=uuid.uuid4(),
        name=payload.name.strip(),
        crm_type=payload.crm_type,
        subdomain_or_base_url=payload.subdomain_or_base_url.strip(),
        encrypted_api_key=encrypt_secret(payload.api_key),
        encrypted_webhook_secret=encrypt_secret(payload.webhook_secret),
        config_metadata=payload.config_metadata,
        is_active=payload.is_active,
        created_at=now_naive,
        updated_at=now_naive,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    cache_integration_config(integration)
    return _serialize_integration(integration)


@router.post("/{integration_id}/sync")
async def trigger_manual_integration_sync(
    integration_id: str,
    sync_request: Optional[IntegrationSyncRequest] = Body(default=None),
    _current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trigger on-demand manual delta-sync reconciliation / backfill (`Section 2.4 & 5.1`)
    for the specified integration (`ADMIN` or `MANAGER`).
    """
    try:
        integration_uuid = uuid.UUID(integration_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid integration_id UUID format",
        ) from exc

    stmt = select(Integration).where(Integration.id == integration_uuid)
    result = await db.execute(stmt)
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )

    req = sync_request or IntegrationSyncRequest()
    summary = await reconcile_integration_closed_tickets(
        db,
        integration,
        backfill_payloads=req.tickets,
        since_timestamp=req.since_timestamp,
    )
    return {
        "status": "COMPLETED",
        **summary,
    }

