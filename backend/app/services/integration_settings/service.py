"""Facade composing the integration-settings storage and provider groups.

Keeps the historical constructor and the union of every provider group's public
methods (``app.api.integrations``, ``app.graph.factories``, the persistence
worker, and the installation service construct this class), so importers of
``app.services.integration_settings`` need no import changes.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.integration_settings.cipher import IntegrationSettingsCipher
from app.services.integration_settings.providers.facebook import FacebookSettingsMixin
from app.services.integration_settings.providers.llm import LlmSettingsMixin
from app.services.integration_settings.providers.tingting import TingtingSettingsMixin
from app.services.integration_settings.providers.zalo import ZaloSettingsMixin
from app.services.integration_settings.storage import StorageMixin


class IntegrationSettingsService(
    StorageMixin,
    ZaloSettingsMixin,
    LlmSettingsMixin,
    FacebookSettingsMixin,
    TingtingSettingsMixin,
):
    """Resolve / admin-view / persist integration credentials per provider group."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        cipher: IntegrationSettingsCipher | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.cipher = cipher or IntegrationSettingsCipher(self.settings)
