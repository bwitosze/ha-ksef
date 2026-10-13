"""Koordynator KSeF - synchronizacja faktur, cache i powiadomienia."""

from __future__ import annotations

import base64
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KsefApi, KsefAuthError, KsefError, KsefNotFoundError, KsefRateLimitError
from .const import (
    CONF_ENVIRONMENT,
    CONF_KSEF_TOKEN,
    CONF_NIP,
    CONF_NOTIFY_SALES,
    CONF_NOTIFY_SERVICE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    ENV_PROD,
    EVENT_NEW_INVOICE,
    EVENT_UPDATED,
    KIND_PURCHASE,
    KIND_SALES,
    MANUAL_REFRESH_COOLDOWN,
    MONTH_NAMES,
    NOTIFY_BATCH_LIMIT,
    PANEL_URL_PATH,
    QR_BASE_URLS,
    SUBJECT_TYPES,
)

_LOGGER = logging.getLogger(__name__)

# Daty w KSeF liczymy po polsku - faktura z 1 października 00:30 czasu
# polskiego to październik, choć w UTC to jeszcze wrzesień.
TZ = ZoneInfo("Europe/Warsaw")

STORAGE_VERSION = 1

type KsefConfigEntry = ConfigEntry[KsefCoordinator]


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _window(now: datetime) -> tuple[datetime, list[str]]:
    """Początek poprzedniego miesiąca i klucze dwóch widocznych miesięcy."""
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_prev = (first_this - timedelta(days=1)).replace(day=1)
    return first_prev, [_month_key(first_prev), _month_key(first_this)]


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def _amount(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _qr_url(environment: str, seller_nip: str, issue_date: str, invoice_hash: str) -> str | None:
    """Link weryfikacyjny KOD I: /invoice/{NIP}/{DD-MM-RRRR}/{SHA-256 base64url}."""
    if not (seller_nip and issue_date and invoice_hash):
        return None
    try:
        digest = base64.b64decode(invoice_hash)
        y, m, d = issue_date[:10].split("-")
    except ValueError:
        return None
    hash_url = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{QR_BASE_URLS[environment]}/invoice/{seller_nip}/{d}-{m}-{y}/{hash_url}"


def normalize(raw: dict[str, Any], kind: str, environment: str) -> dict[str, Any]:
    """Spłaszcz metadane KSeF do tego, czego potrzebuje panel."""
    seller = raw.get("seller") or {}
    buyer = raw.get("buyer") or {}
    buyer_id = buyer.get("identifier") or {}
    if kind == KIND_PURCHASE:
        party_name, party_nip = seller.get("name"), seller.get("nip")
    else:
        party_name, party_nip = buyer.get("name"), buyer_id.get("value")
    issue_date = str(raw.get("issueDate") or "")[:10]
    return {
        "ksef_number": raw.get("ksefNumber"),
        "invoice_number": raw.get("invoiceNumber"),
        "kind": kind,
        "issue_date": issue_date,
        "month": issue_date[:7],
        "acquisition_date": raw.get("acquisitionDate") or raw.get("invoicingDate"),
        "counterparty_name": party_name,
        "counterparty_nip": party_nip,
        "net_amount": _amount(raw.get("netAmount")),
        "vat_amount": _amount(raw.get("vatAmount")),
        "gross_amount": _amount(raw.get("grossAmount")),
        "currency": raw.get("currency") or "PLN",
        "invoice_type": raw.get("invoiceType"),
        "form": (raw.get("formCode") or {}).get("systemCode"),
        "qr_url": _qr_url(environment, seller.get("nip"), issue_date, raw.get("invoiceHash")),
    }


class KsefCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]]]]):
    """Trzyma faktury z poprzedniego i bieżącego miesiąca.

    Dane są utrwalane w ``.storage/ksef.<entry_id>``: po restarcie HA panel
    od razu ma listę, a zbiór znanych numerów KSeF chroni przed wysłaniem
    pusha o fakturach, o których już było powiadomienie.
    """

    config_entry: KsefConfigEntry

    def __init__(self, hass: HomeAssistant, entry: KsefConfigEntry) -> None:
        interval = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_NIP]}",
            update_interval=timedelta(minutes=interval),
            config_entry=entry,
        )
        self.environment: str = entry.data.get(CONF_ENVIRONMENT, ENV_PROD)
        self.nip: str = entry.data[CONF_NIP]
        self.api = KsefApi(
            async_get_clientsession(hass),
            self.environment,
            self.nip,
            entry.data[CONF_KSEF_TOKEN],
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._invoices: dict[str, dict[str, Any]] = {}
        self._known: set[str] = set()
        self._seeded = False
        self.last_update: str | None = None
        self.last_error: str | None = None
        self._blocked_until = 0.0
        self._last_query = 0.0
        self.xml_dir = Path(hass.config.path(".storage", "ksef_xml", entry.entry_id))

    # ------------------------------------------------------------- stan

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._invoices = stored.get("invoices") or {}
        self._known = set(stored.get("known") or [])
        self._seeded = bool(stored.get("seeded"))
        self.last_update = stored.get("last_update")
        self.async_set_updated_data(self._snapshot())

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "invoices": self._invoices,
                "known": sorted(self._known),
                "seeded": self._seeded,
                "last_update": self.last_update,
            }
        )

    def _snapshot(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {KIND_PURCHASE: [], KIND_SALES: []}
        for invoice in self._invoices.values():
            result[invoice["kind"]].append(invoice)
        for items in result.values():
            items.sort(
                key=lambda inv: (inv.get("issue_date") or "", inv.get("acquisition_date") or ""),
                reverse=True,
            )
        return result

    @property
    def months(self) -> list[str]:
        return _window(dt_util.now(TZ))[1]

    def month_total(self, kind: str, month: str) -> tuple[int, float]:
        items = [
            inv for inv in (self.data or {}).get(kind, [])
            if inv["month"] == month and inv.get("currency") == "PLN"
        ]
        return len(items), round(sum(inv.get("gross_amount") or 0 for inv in items), 2)

    # ------------------------------------------------------- odświeżanie

    async def async_manual_refresh(self) -> None:
        """Przycisk "Odśwież" w panelu - z ochroną limitu zapytań."""
        wait = MANUAL_REFRESH_COOLDOWN - (time.monotonic() - self._last_query)
        if wait > 0:
            raise HomeAssistantError(
                f"Dane są świeże - kolejne odświeżenie możliwe za {int(wait) + 1} s "
                "(KSeF pozwala na 20 zapytań na godzinę)."
            )
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]]]:
        if time.time() < self._blocked_until:
            # Po 429 KSeF wydłuża blokadę przy każdym kolejnym naruszeniu,
            # więc w okresie Retry-After w ogóle nie pukamy.
            return self._snapshot()

        now = dt_util.now(TZ)
        date_from, months = _window(now)
        fetched: dict[str, dict[str, Any]] = {}
        self._last_query = time.monotonic()
        try:
            for kind, subject in SUBJECT_TYPES.items():
                for raw in await self.api.query_metadata(subject, date_from, now):
                    invoice = normalize(raw, kind, self.environment)
                    if invoice["ksef_number"] and invoice["month"] in months:
                        fetched[invoice["ksef_number"]] = invoice
        except KsefAuthError as err:
            self.last_error = str(err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except KsefRateLimitError as err:
            self._blocked_until = time.time() + err.retry_after
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err
        except KsefError as err:
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err

        new = [inv for number, inv in fetched.items() if number not in self._known]
        self._invoices = fetched
        # Znane numery to dokładnie zawartość okna - po zmianie miesiąca
        # faktury sprzed dwóch miesięcy wypadają i zbiór nie rośnie bez końca.
        self._known = set(fetched)
        first_run = not self._seeded
        self._seeded = True
        self.last_update = dt_util.utcnow().isoformat()
        self.last_error = None
        await self._async_save()
        self._prune_xml_cache()

        if new and not first_run:
            # Pierwsza synchronizacja zna wszystkie faktury z dwóch miesięcy -
            # push o każdej z nich byłby spamem, więc tylko je zapamiętujemy.
            await self._announce(new)
        self.hass.bus.async_fire(EVENT_UPDATED, {"entry_id": self.config_entry.entry_id})
        return self._snapshot()

    # ----------------------------------------------------- powiadomienia

    async def _announce(self, new: list[dict[str, Any]]) -> None:
        for invoice in new:
            self.hass.bus.async_fire(
                EVENT_NEW_INVOICE, {"entry_id": self.config_entry.entry_id, **invoice}
            )

        notify_sales = self.config_entry.options.get(CONF_NOTIFY_SALES, False)
        to_push = [
            inv for inv in new
            if inv["kind"] == KIND_PURCHASE or notify_sales
        ]
        service = self.config_entry.options.get(
            CONF_NOTIFY_SERVICE,
            self.config_entry.data.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE),
        )
        if not to_push or not service:
            return

        if len(to_push) > NOTIFY_BATCH_LIMIT:
            total = sum(inv.get("gross_amount") or 0 for inv in to_push)
            title = f"KSeF: {len(to_push)} nowe faktury"
            message = f"Łącznie {_fmt_money(total)} zł brutto. Szczegóły w panelu KSeF."
            await self._push(service, title, message, "ksef-batch")
            return

        for inv in to_push:
            label = "Nowa faktura" if inv["kind"] == KIND_PURCHASE else "Wystawiona faktura"
            party = inv.get("counterparty_name") or inv.get("counterparty_nip") or "?"
            amount = _fmt_money(inv.get("gross_amount"))
            currency = inv.get("currency") or "PLN"
            message = (
                f"{party}: {amount} {'zł' if currency == 'PLN' else currency} brutto\n"
                f"{inv.get('invoice_number')} z {_fmt_date(inv.get('issue_date'))}"
            )
            await self._push(service, f"KSeF: {label}", message, inv["ksef_number"])

    async def _push(self, service: str, title: str, message: str, tag: str) -> None:
        domain, _, name = service.partition(".")
        if not name:
            domain, name = "notify", service
        try:
            await self.hass.services.async_call(
                domain,
                name,
                {
                    "title": title,
                    "message": message,
                    # clickAction (Android) / url (iOS) - tapnięcie otwiera panel.
                    "data": {
                        "clickAction": f"/{PANEL_URL_PATH}",
                        "url": f"/{PANEL_URL_PATH}",
                        "tag": tag,
                        "group": "ksef",
                    },
                },
                blocking=True,
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Nie udało się wysłać powiadomienia przez %s: %s", service, err)

    # --------------------------------------------------------------- XML

    def get_invoice(self, ksef_number: str) -> dict[str, Any] | None:
        return self._invoices.get(ksef_number)

    async def async_get_xml(self, ksef_number: str) -> bytes:
        """XML faktury - z cache na dysku, a w razie braku z KSeF.

        Limit pobrań to 64 na godzinę, a faktura w KSeF jest niezmienna,
        więc każdy plik ściągamy dokładnie raz.
        """
        path = self.xml_dir / f"{ksef_number}.xml"
        cached = await self.hass.async_add_executor_job(_read_file, path)
        if cached is not None:
            return cached
        try:
            content = await self.api.download_invoice(ksef_number)
        except KsefNotFoundError as err:
            raise HomeAssistantError(
                "Faktura jeszcze nie jest dostępna w KSeF - spróbuj za kilka minut."
            ) from err
        except KsefError as err:
            raise HomeAssistantError(str(err)) from err
        await self.hass.async_add_executor_job(_write_file, path, content)
        return content

    def _prune_xml_cache(self) -> None:
        keep = set(self._invoices)

        def _prune() -> None:
            if not self.xml_dir.is_dir():
                return
            for file in self.xml_dir.glob("*.xml"):
                if file.stem not in keep:
                    file.unlink(missing_ok=True)

        self.hass.async_add_executor_job(_prune)

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()

        def _rm() -> None:
            if self.xml_dir.is_dir():
                for file in self.xml_dir.glob("*"):
                    file.unlink(missing_ok=True)
                self.xml_dir.rmdir()

        await self.hass.async_add_executor_job(_rm)


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")


def _fmt_date(value: str | None) -> str:
    if not value:
        return "?"
    y, m, d = value[:10].split("-")
    return f"{d}.{m}.{y}"
