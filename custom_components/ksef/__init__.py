"""Integracja KSeF (Krajowy System e-Faktur) dla Home Assistanta.

Co robi:
* co 15 minut pobiera z KSeF metadane faktur zakupowych i sprzedażowych
  z poprzedniego i bieżącego miesiąca,
* przy nowej fakturze zakupowej wysyła push przez wybraną usługę notify
  i odpala zdarzenie ``ksef_new_invoice``,
* rejestruje panel "KSeF" w menu bocznym z listą faktur, ręcznym
  odświeżaniem i pobieraniem XML/PDF.

Panel czyta dane przez WebSocket (``ksef/invoices``, ``ksef/refresh``),
a pliki przez widok HTTP ``/api/ksef/<entry_id>/<numer KSeF>.xml``.
PDF składa w przeglądarce oficjalny generator MF dołączony w ``frontend/``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    EVENT_UPDATED,
    KIND_PURCHASE,
    KIND_SALES,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    SERVICE_REFRESH,
    STATIC_URL,
)
from .coordinator import KsefConfigEntry, KsefCoordinator, XmlRateLimited, month_label

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FRONTEND_DIR = Path(__file__).parent / "frontend"
KSEF_NUMBER_RE = re.compile(r"^[0-9]{10}-[0-9]{8}-[0-9A-F]{6}-?[0-9A-F]{6}-[0-9A-F]{2}$")

DATA_SETUP_DONE = f"{DOMAIN}_setup_done"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Rzeczy wspólne dla wszystkich wpisów: pliki panelu, WebSocket, HTTP."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    hass.http.register_view(KsefInvoiceXmlView())
    websocket_api.async_register_command(hass, ws_invoices)
    websocket_api.async_register_command(hass, ws_refresh)
    websocket_api.async_register_command(hass, ws_subscribe)
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KsefConfigEntry) -> bool:
    """Skonfiguruj wpis (jeden NIP)."""
    coordinator = KsefCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown_retry)
    # DataUpdateCoordinator planuje kolejne odświeżenia tylko, gdy ma
    # słuchaczy. Bez własnego słuchacza wyłączenie obu sensorów zatrzymałoby
    # odpytywanie KSeF, a z nim pushe i aktualizację panelu.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    # Pierwsze odświeżenie w tle: po restarcie HA panel ma dane z cache,
    # a chwilowy brak KSeF nie blokuje startu integracji.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN} first refresh"
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await _async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KsefConfigEntry) -> bool:
    """Odłącz wpis."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.api.async_close()
        others = [
            e for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not others:
            frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: KsefConfigEntry) -> None:
    """Usunięcie integracji - kasujemy cache faktur i XML-i."""
    coordinator = KsefCoordinator(hass, entry)
    await coordinator.async_remove_storage()


async def _async_reload_entry(hass: HomeAssistant, entry: KsefConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    manifest_version = await hass.async_add_executor_job(_frontend_version)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_WEBCOMPONENT,
        sidebar_title="KSeF",
        sidebar_icon="mdi:receipt-text-outline",
        # ?v= wymusza pobranie nowej wersji panelu po zmianie pliku -
        # bez tego przeglądarka trzymałaby starą z cache.
        module_url=f"{STATIC_URL}/ksef-panel.js?v={manifest_version}",
        embed_iframe=False,
        require_admin=False,
        config={"static_url": STATIC_URL, "version": manifest_version},
    )


def _frontend_version() -> str:
    """Znacznik wersji plików panelu (czas modyfikacji)."""
    stamps = [
        int(path.stat().st_mtime)
        for path in FRONTEND_DIR.glob("*.js")
    ]
    return str(max(stamps, default=0))


def _coordinators(hass: HomeAssistant) -> list[KsefCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


def _coordinator_for(hass: HomeAssistant, entry_id: str) -> KsefCoordinator | None:
    for coordinator in _coordinators(hass):
        if coordinator.config_entry.entry_id == entry_id:
            return coordinator
    return None


# ------------------------------------------------------------------ WebSocket


@websocket_api.websocket_command({vol.Required("type"): "ksef/invoices"})
@callback
def ws_invoices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Faktury ze wszystkich wpisów, gotowe do wyświetlenia w panelu."""
    coordinators = _coordinators(hass)
    invoices: dict[str, list[dict[str, Any]]] = {KIND_PURCHASE: [], KIND_SALES: []}
    months: list[str] = []
    errors: list[str] = []
    last_updates: list[str] = []
    environments: set[str] = set()
    for coordinator in coordinators:
        entry_id = coordinator.config_entry.entry_id
        environments.add(coordinator.environment)
        # Środowisko przy każdej fakturze: przy wpisie produkcyjnym i testowym
        # naraz panel oznacza faktury testowe i nie wlicza ich do sum.
        for kind, items in (coordinator.data or {}).items():
            invoices[kind].extend(
                {**inv, "entry_id": entry_id, "environment": coordinator.environment}
                for inv in items
            )
        months = coordinator.months
        if coordinator.last_error:
            errors.append(coordinator.last_error)
        if coordinator.last_update:
            last_updates.append(coordinator.last_update)

    connection.send_result(
        msg["id"],
        {
            "entries": [
                {
                    "entry_id": c.config_entry.entry_id,
                    "title": c.config_entry.title,
                    "nip": c.nip,
                }
                for c in coordinators
            ],
            "months": [{"key": key, "label": month_label(key)} for key in months],
            "invoices": invoices,
            "last_update": min(last_updates) if last_updates else None,
            "last_error": " | ".join(errors) or None,
            # Pojedyncze środowisko tylko, gdy wszystkie wpisy są z jednego.
            "environment": environments.pop() if len(environments) == 1 else None,
            "mixed_environments": len(environments) > 1,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "ksef/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Powiadamiaj panel o każdym odświeżeniu.

    Zwykłe ``subscribe_events`` na ``ksef_updated`` HA odrzuca dla kont bez
    uprawnień administratora (zdarzenie spoza listy dozwolonych), a panel
    jest dostępny dla wszystkich zalogowanych. Własna komenda wysyła tylko
    identyfikator wpisu - dane panel i tak pobiera przez ``ksef/invoices``.
    """

    @callback
    def _forward(event: Event) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"entry_id": event.data.get("entry_id")}
            )
        )

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_UPDATED, _forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "ksef/refresh"})
@websocket_api.async_response
async def ws_refresh(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Przycisk "Odśwież" w panelu."""
    try:
        for coordinator in _coordinators(hass):
            await coordinator.async_manual_refresh()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "refresh_failed", str(err))
        return
    connection.send_result(msg["id"])


# ----------------------------------------------------------------------- HTTP


class KsefInvoiceXmlView(HomeAssistantView):
    """XML faktury. Wymaga zalogowania (panel używa podpisanej ścieżki)."""

    url = "/api/ksef/{entry_id}/{filename}"
    name = "api:ksef:invoice"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str, filename: str) -> web.Response:
        hass = request.app[KEY_HASS]
        ksef_number, _, ext = filename.rpartition(".")
        if ext != "xml" or not KSEF_NUMBER_RE.match(ksef_number):
            return web.Response(status=404, text="Nieznany plik")
        coordinator = _coordinator_for(hass, entry_id)
        if coordinator is None or coordinator.get_invoice(ksef_number) is None:
            # Pobieramy tylko faktury z listy - widok nie może służyć do
            # odpytywania KSeF o dowolne numery.
            return web.Response(status=404, text="Brak faktury na liście")
        try:
            content = await coordinator.async_get_xml(ksef_number)
        except XmlRateLimited as err:
            return web.Response(
                status=429,
                text=str(err),
                headers={"Retry-After": str(err.retry_after)},
            )
        except HomeAssistantError as err:
            return web.Response(status=502, text=str(err))
        return web.Response(
            body=content,
            content_type="application/xml",
            charset="utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{ksef_number}.xml"',
                "Cache-Control": "no-store",
            },
        )


# --------------------------------------------------------------------- usługi


def _async_register_services(hass: HomeAssistant) -> None:
    async def _handle_refresh(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            await coordinator.async_manual_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)
