"""Sensory KSeF - liczba faktur w bieżącym miesiącu."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KIND_PURCHASE, KIND_SALES, PANEL_URL_PATH
from .coordinator import KsefConfigEntry, KsefCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KsefConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        KsefMonthSensor(coordinator, kind) for kind in (KIND_PURCHASE, KIND_SALES)
    )


class KsefMonthSensor(CoordinatorEntity[KsefCoordinator], SensorEntity):
    """Ile faktur danego rodzaju wpłynęło w bieżącym miesiącu."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "faktur"
    _attr_icon = "mdi:receipt-text-outline"

    def __init__(self, coordinator: KsefCoordinator, kind: str) -> None:
        super().__init__(coordinator)
        self._kind = kind
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{kind}_current_month"
        self._attr_translation_key = f"{kind}_current_month"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"KSeF {coordinator.nip}",
            manufacturer="Ministerstwo Finansów",
            model="Krajowy System e-Faktur",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"homeassistant://{PANEL_URL_PATH}",
        )

    @property
    def available(self) -> bool:
        # Dane z cache są wiarygodne także przy chwilowym braku KSeF.
        return self.coordinator.data is not None

    @property
    def native_value(self) -> int:
        count, _ = self.coordinator.month_total(self._kind, self.coordinator.months[-1])
        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self.coordinator.months
        count_prev, gross_prev = self.coordinator.month_total(self._kind, months[0])
        _, gross = self.coordinator.month_total(self._kind, months[-1])
        return {
            "gross_total_pln": gross,
            "previous_month_count": count_prev,
            "previous_month_gross_total_pln": gross_prev,
            "last_update": self.coordinator.last_update,
            "last_error": self.coordinator.last_error,
        }
