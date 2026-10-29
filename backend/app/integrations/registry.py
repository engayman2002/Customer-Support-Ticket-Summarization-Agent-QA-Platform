from __future__ import annotations

from typing import Dict, Union

from app.integrations.base import BaseCRMConnector
from app.integrations.custom import CustomCRMConnector
from app.integrations.freshdesk import FreshdeskConnector
from app.integrations.intercom import IntercomConnector
from app.integrations.zendesk import ZendeskConnector
from app.models.enums import CrmType


class ProviderRegistry:
    """
    Strategy Registry resolving a `CrmType` enum or provider slug (`zendesk`, `intercom`,
    `freshdesk`, `custom`) to its concrete `BaseCRMConnector` instance.
    """

    _CONNECTORS: Dict[CrmType, BaseCRMConnector] = {
        CrmType.ZENDESK: ZendeskConnector(),
        CrmType.FRESHDESK: FreshdeskConnector(),
        CrmType.INTERCOM: IntercomConnector(),
        CrmType.CUSTOM: CustomCRMConnector(),
    }

    @classmethod
    def get_connector(cls, provider: Union[CrmType, str]) -> BaseCRMConnector:
        if isinstance(provider, CrmType):
            crm_type = provider
        else:
            normalized = str(provider or "").strip().upper()
            try:
                crm_type = CrmType(normalized)
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported CRM provider '{provider}'. Supported: {[c.value for c in CrmType]}"
                ) from exc

        return cls._CONNECTORS[crm_type]


def get_connector(provider: Union[CrmType, str]) -> BaseCRMConnector:
    return ProviderRegistry.get_connector(provider)

