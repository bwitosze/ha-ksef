"""Stałe integracji KSeF."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ksef"

CONF_NIP: Final = "nip"
CONF_KSEF_TOKEN: Final = "ksef_token"
CONF_ENVIRONMENT: Final = "environment"
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_NOTIFY_SALES: Final = "notify_sales"
CONF_SCAN_INTERVAL_MINUTES: Final = "scan_interval_minutes"

ENV_PROD: Final = "prod"
ENV_DEMO: Final = "demo"
ENV_TEST: Final = "test"

API_BASE_URLS: Final[dict[str, str]] = {
    ENV_PROD: "https://api.ksef.mf.gov.pl/v2",
    ENV_DEMO: "https://api-demo.ksef.mf.gov.pl/v2",
    ENV_TEST: "https://api-test.ksef.mf.gov.pl/v2",
}

# Host linku weryfikacyjnego (KOD I na wydruku faktury).
QR_BASE_URLS: Final[dict[str, str]] = {
    ENV_PROD: "https://qr.ksef.mf.gov.pl",
    ENV_DEMO: "https://qr-demo.ksef.mf.gov.pl",
    ENV_TEST: "https://qr-test.ksef.mf.gov.pl",
}

# Pusto = bez pushy. Podpowiedź w formularzu: notify.mobile_app_<telefon>.
DEFAULT_NOTIFY_SERVICE: Final = ""
# MF prosi, żeby nie odpytywać częściej niż co 15 minut na typ podmiotu.
# Jedno odświeżenie to dwa zapytania (zakupowe + sprzedażowe) z limitu 20/h.
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 15
MIN_SCAN_INTERVAL_MINUTES: Final = 15

# Ręczne "Odśwież" z panelu nie częściej niż raz na tyle sekund -
# kilka kliknięć pod rząd potrafiłoby zjeść godzinny limit zapytań.
MANUAL_REFRESH_COOLDOWN: Final = 120

KIND_PURCHASE: Final = "purchase"
KIND_SALES: Final = "sales"

# Rola mojego NIP-u na fakturze w zapytaniu o metadane.
SUBJECT_TYPES: Final[dict[str, str]] = {
    KIND_PURCHASE: "Subject2",  # jestem nabywcą
    KIND_SALES: "Subject1",  # jestem sprzedawcą
}

EVENT_NEW_INVOICE: Final = "ksef_new_invoice"
EVENT_UPDATED: Final = "ksef_updated"

SERVICE_REFRESH: Final = "refresh"

PANEL_URL_PATH: Final = "ksef"
PANEL_WEBCOMPONENT: Final = "ksef-panel"
STATIC_URL: Final = "/ksef_static"

# Powyżej tylu nowych faktur naraz wysyłamy jedno zbiorcze powiadomienie.
NOTIFY_BATCH_LIMIT: Final = 3

MONTH_NAMES: Final = (
    "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
    "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień",
)
