"""Plug-and-play external CRM Connector Strategy & Adapter layer."""

from app.integrations.base import BaseCRMConnector
from app.integrations.custom import CustomCRMConnector
from app.integrations.freshdesk import FreshdeskConnector
from app.integrations.intercom import IntercomConnector
from app.integrations.registry import ProviderRegistry, get_connector
from app.integrations.zendesk import ZendeskConnector

__all__ = [
    "BaseCRMConnector",
    "ZendeskConnector",
    "IntercomConnector",
    "FreshdeskConnector",
    "CustomCRMConnector",
    "ProviderRegistry",
    "get_connector",
]

