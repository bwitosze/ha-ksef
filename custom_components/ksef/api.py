"""Klient API KSeF 2.0 (Krajowy System e-Faktur).

Źródła: oficjalna dokumentacja github.com/CIRFMF/ksef-api (dawniej ksef-docs)
oraz specyfikacja OpenAPI https://api.ksef.mf.gov.pl/docs/v2/openapi.json,
stan z października 2026 (changelog v2.8.1).

Logowanie tokenem KSeF, w skrócie:

1. ``POST /auth/challenge``            -> challenge + timestampMs
2. ``GET  /security/public-key-certificates`` -> klucz z usage KsefTokenEncryption
3. szyfrujemy ``"<token>|<timestampMs>"`` RSA-OAEP (SHA-256, MGF1 SHA-256)
4. ``POST /auth/ksef-token``           -> referenceNumber + authenticationToken
5. ``GET  /auth/{referenceNumber}``    -> czekamy na status 200 (Bearer = authenticationToken)
6. ``POST /auth/token/redeem``         -> accessToken (kilkanaście minut) + refreshToken (7 dni)
7. ``POST /auth/token/refresh``        -> nowy accessToken (Bearer = refreshToken)

Limity na produkcji są ciasne i liczone na parę (NIP, IP): zapytanie
o metadane faktur to 20 na godzinę, pobranie XML faktury 64 na godzinę.
Dlatego klient nic nie robi "przy okazji" - koordynator wywołuje go
rzadko, a XML-e są cache'owane na dysku.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from .const import API_BASE_URLS

_LOGGER = logging.getLogger(__name__)

TIMEOUT = ClientTimeout(total=30)

# Ułamek sekund: KSeF podaje 7 cyfr, fromisoformat przyjmuje najwyżej 6.
_FRACTION_RE = re.compile(r"\.\d+")

# Ile razy i jak często pytamy o status uwierzytelnienia (krok 5).
AUTH_POLL_ATTEMPTS = 20
AUTH_POLL_INTERVAL = 1.0

# Odśwież access token, jeśli wygasa szybciej niż za tyle sekund.
ACCESS_TOKEN_MARGIN = 60

PAGE_SIZE = 250  # maksimum dopuszczalne przez API (10..250)

# Do tylu sekund Retry-After czekamy na miejscu zamiast przerywać odświeżanie.
SHORT_RETRY_LIMIT = 30

# Kody błędów z ExceptionResponse, na które reagujemy osobno.
ERR_UNKNOWN_KEY = 21470  # nieznany lub unieważniony publicKeyId - rotacja kluczy MF
ERR_TOKENS_REDEEMED = 21301  # sesja unieważniona / token KSeF unieważniony
ERR_INVOICE_NOT_FOUND = 21164
ERR_INVOICE_NOT_READY = 21165  # przetworzona, ale jeszcze niedostępna do pobrania

# Statusy operacji uwierzytelnienia (GET /auth/{ref}).
AUTH_IN_PROGRESS = 100
AUTH_OK = 200
AUTH_FATAL = {415, 425, 450, 460, 470, 480}


class KsefError(Exception):
    """Błąd komunikacji z KSeF."""


class KsefAuthError(KsefError):
    """Token KSeF odrzucony lub unieważniony - potrzebny nowy token."""


class KsefRateLimitError(KsefError):
    """Przekroczony limit zapytań (HTTP 429)."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class KsefNotFoundError(KsefError):
    """Faktura nie istnieje albo jeszcze nie jest dostępna."""


@dataclass
class _Token:
    token: str
    valid_until: float  # epoch, sekundy

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> _Token:
        return cls(data["token"], _parse_ts(data.get("validUntil")))

    def valid_for(self, seconds: float) -> bool:
        return self.valid_until - time.time() > seconds


def _parse_ts(value: str | None) -> float:
    """validUntil ma 7 cyfr ułamka sekund, czego fromisoformat w 3.12 nie lubi."""
    if not value:
        return time.time() + 600
    text = _FRACTION_RE.sub(lambda m: m.group(0)[:7], value.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return time.time() + 600
    if parsed.tzinfo is None:
        # KSeF podaje strefę zawsze; gdyby nie - to UTC, nie czas lokalny.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _error_codes(payload: Any) -> list[int]:
    """Wyciągnij kody z ExceptionResponse albo problem+json."""
    codes: list[int] = []
    if not isinstance(payload, dict):
        return codes
    exc = payload.get("exception") or {}
    for item in exc.get("exceptionDetailList") or []:
        try:
            codes.append(int(item.get("exceptionCode")))
        except (TypeError, ValueError):
            pass
    for item in payload.get("errors") or []:
        if isinstance(item, dict):
            try:
                codes.append(int(item.get("code")))
            except (TypeError, ValueError):
                pass
    return codes


def _error_text(payload: Any) -> str:
    if isinstance(payload, dict):
        exc = payload.get("exception") or {}
        parts = [
            f"{item.get('exceptionCode')}: {item.get('exceptionDescription')}"
            + (f" ({'; '.join(item['details'])})" if item.get("details") else "")
            for item in exc.get("exceptionDetailList") or []
        ]
        if parts:
            return " | ".join(parts)
        if payload.get("title") or payload.get("detail"):
            return f"{payload.get('title', '')} {payload.get('detail', '')}".strip()
    return str(payload)[:300]


class KsefApi:
    """Sesja z KSeF dla jednego kontekstu (NIP)."""

    def __init__(
        self, session: ClientSession, environment: str, nip: str, ksef_token: str
    ) -> None:
        self._session = session
        self._base = API_BASE_URLS[environment]
        self._nip = nip
        self._ksef_token = ksef_token
        self._access: _Token | None = None
        self._refresh: _Token | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ HTTP

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> tuple[ClientResponse, Any]:
        headers = {"Accept": accept}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            resp = await self._session.request(
                method,
                f"{self._base}{path}",
                headers=headers,
                json=json,
                params=params,
                timeout=TIMEOUT,
            )
            async with resp:
                if accept == "application/json" or resp.status >= 400:
                    try:
                        body: Any = await resp.json(content_type=None)
                    except ValueError:
                        body = await resp.text()
                else:
                    body = await resp.read()
        except (ClientError, TimeoutError) as err:
            raise KsefError(f"Brak połączenia z KSeF: {err}") from err

        if warning := resp.headers.get("X-System-Warning"):
            _LOGGER.info("KSeF ostrzega: %s", warning)

        if resp.status == 429:
            try:
                retry_after = int(resp.headers.get("Retry-After", "60"))
            except ValueError:
                retry_after = 60
            raise KsefRateLimitError(
                f"KSeF: przekroczony limit zapytań, ponowienie za {retry_after} s",
                retry_after,
            )
        if resp.status == 401:
            raise KsefAuthError(f"KSeF odrzucił autoryzację ({path})")
        if resp.status >= 400:
            codes = _error_codes(body)
            err_cls: type[KsefError] = KsefError
            if ERR_TOKENS_REDEEMED in codes:
                err_cls = KsefAuthError
            elif ERR_INVOICE_NOT_FOUND in codes or ERR_INVOICE_NOT_READY in codes:
                err_cls = KsefNotFoundError
            error = err_cls(f"KSeF {resp.status} {path}: {_error_text(body)}")
            error.codes = codes  # type: ignore[attr-defined]
            raise error
        return resp, body

    # ------------------------------------------------------------ logowanie

    async def _encryption_key(self) -> tuple[Any, str]:
        _, certs = await self._request("GET", "/security/public-key-certificates")
        now = datetime.now(timezone.utc).timestamp()
        usable = [
            c
            for c in certs or []
            if "KsefTokenEncryption" in (c.get("usage") or [])
            and _parse_ts(c.get("validFrom")) <= now < _parse_ts(c.get("validTo"))
        ]
        if not usable:
            raise KsefError("KSeF nie zwrócił ważnego klucza do szyfrowania tokena")
        # Przy rotacji może być kilka ważnych - bierzemy najnowszy.
        cert = max(usable, key=lambda c: _parse_ts(c.get("validFrom")))
        public_key = x509.load_der_x509_certificate(
            base64.b64decode(cert["certificate"])
        ).public_key()
        return public_key, cert.get("publicKeyId")

    async def _authenticate(self) -> None:
        """Pełne logowanie tokenem KSeF (kroki 1-6)."""
        _, challenge = await self._request("POST", "/auth/challenge")
        public_key, public_key_id = await self._encryption_key()

        plaintext = f"{self._ksef_token}|{challenge['timestampMs']}".encode()
        encrypted = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        body = {
            "challenge": challenge["challenge"],
            "contextIdentifier": {"type": "Nip", "value": self._nip},
            "encryptedToken": base64.b64encode(encrypted).decode(),
            "publicKeyId": public_key_id,
        }
        try:
            _, started = await self._request("POST", "/auth/ksef-token", json=body)
        except KsefError as err:
            if ERR_UNKNOWN_KEY in getattr(err, "codes", []):
                raise KsefError("KSeF zmienił klucz szyfrujący - ponowię") from err
            if getattr(err, "codes", None):
                raise KsefAuthError(str(err)) from err
            raise

        reference = started["referenceNumber"]
        auth_token = started["authenticationToken"]["token"]

        for _ in range(AUTH_POLL_ATTEMPTS):
            _, status = await self._request(
                "GET", f"/auth/{reference}", bearer=auth_token
            )
            info = status.get("status") or {}
            code = info.get("code")
            if code == AUTH_OK:
                break
            if code in AUTH_FATAL:
                details = "; ".join(info.get("details") or [])
                raise KsefAuthError(
                    f"KSeF odrzucił token ({code}: {info.get('description')}"
                    f"{' - ' + details if details else ''})"
                )
            if code != AUTH_IN_PROGRESS:
                raise KsefError(
                    f"Uwierzytelnienie nieudane ({code}: {info.get('description')})"
                )
            await asyncio.sleep(AUTH_POLL_INTERVAL)
        else:
            raise KsefError("KSeF nie potwierdził uwierzytelnienia w czasie")

        _, tokens = await self._request(
            "POST", "/auth/token/redeem", bearer=auth_token
        )
        self._access = _Token.from_json(tokens["accessToken"])
        self._refresh = _Token.from_json(tokens["refreshToken"])
        _LOGGER.debug("Zalogowano do KSeF, NIP %s", self._nip)

    async def _access_token(self) -> str:
        async with self._lock:
            if self._access and self._access.valid_for(ACCESS_TOKEN_MARGIN):
                return self._access.token
            if self._refresh and self._refresh.valid_for(ACCESS_TOKEN_MARGIN):
                try:
                    _, data = await self._request(
                        "POST", "/auth/token/refresh", bearer=self._refresh.token
                    )
                    self._access = _Token.from_json(data["accessToken"])
                    return self._access.token
                except KsefRateLimitError:
                    raise
                except KsefError as err:
                    # Refresh token bywa unieważniony po stronie MF - wtedy
                    # zwyczajnie logujemy się od nowa tokenem KSeF.
                    _LOGGER.debug("Odświeżenie tokena nieudane, loguję od nowa: %s", err)
                    self._refresh = None
            await self._authenticate()
            assert self._access is not None
            return self._access.token

    async def async_validate(self) -> None:
        """Zaloguj się - używane przez config flow."""
        self._access = None
        self._refresh = None
        await self._access_token()

    # -------------------------------------------------------------- faktury

    async def query_metadata(
        self, subject_type: str, date_from: datetime, date_to: datetime
    ) -> list[dict[str, Any]]:
        """Metadane faktur z zakresu dat wystawienia.

        ``subject_type``: Subject1 = sprzedawca (moje sprzedażowe),
        Subject2 = nabywca (moje zakupowe). Każda strona to jedno zapytanie
        z limitu 20/h, więc w praktyce wszystko mieści się na pierwszej.
        """
        body = {
            "subjectType": subject_type,
            "dateRange": {
                "dateType": "Issue",
                "from": date_from.isoformat(timespec="seconds"),
                "to": date_to.isoformat(timespec="seconds"),
            },
        }
        result: dict[str, dict[str, Any]] = {}
        page = 0
        short_waits = 0
        while True:
            token = await self._access_token()
            try:
                _, data = await self._request(
                    "POST",
                    "/invoices/query/metadata",
                    bearer=token,
                    json=body,
                    params={"pageOffset": page, "pageSize": PAGE_SIZE, "sortOrder": "Asc"},
                )
            except KsefRateLimitError as err:
                # Limit sekundowy/minutowy przy wielu stronach pod rząd -
                # krótka przerwa wystarczy. Blokadę godzinną oddajemy wyżej.
                if err.retry_after > SHORT_RETRY_LIMIT or short_waits >= 3:
                    raise
                short_waits += 1
                await asyncio.sleep(err.retry_after + 1)
                continue
            invoices = data.get("invoices") or []
            for invoice in invoices:
                if number := invoice.get("ksefNumber"):
                    result[number] = invoice
            if not data.get("hasMore") or not invoices:
                break
            if data.get("isTruncated"):
                # Limit 10 000 rekordów na zestaw filtrów - przesuwamy początek.
                last = invoices[-1].get("issueDate")
                body["dateRange"]["from"] = f"{last}T00:00:00+00:00"
                page = 0
            else:
                page += 1
        return list(result.values())

    async def download_invoice(self, ksef_number: str) -> bytes:
        """Oryginalny XML faktury."""
        token = await self._access_token()
        _, content = await self._request(
            "GET",
            f"/invoices/ksef/{ksef_number}",
            bearer=token,
            accept="application/xml",
        )
        return content

    async def async_close(self) -> None:
        """Unieważnij refresh token przy wyładowaniu integracji."""
        if not (self._access and self._access.valid_for(5)):
            return
        try:
            await self._request(
                "DELETE", "/auth/sessions/current", bearer=self._access.token
            )
        except KsefError as err:
            _LOGGER.debug("Nie udało się zamknąć sesji KSeF: %s", err)
