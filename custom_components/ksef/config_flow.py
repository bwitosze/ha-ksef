"""Konfiguracja KSeF przez UI - NIP, token KSeF i środowisko."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import KsefApi, KsefAuthError, KsefError
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
    ENV_DEMO,
    ENV_PROD,
    ENV_TEST,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .coordinator import KsefConfigEntry

_LOGGER = logging.getLogger(__name__)

NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _normalize_nip(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _valid_nip(nip: str) -> bool:
    if len(nip) != 10:
        return False
    checksum = sum(int(d) * w for d, w in zip(nip, NIP_WEIGHTS)) % 11
    return checksum != 10 and checksum == int(nip[9])


def _token_schema() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _env_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[ENV_PROD, ENV_DEMO, ENV_TEST],
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_ENVIRONMENT,
        )
    )


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NIP): str,
        vol.Required(CONF_KSEF_TOKEN): _token_schema(),
        vol.Required(CONF_ENVIRONMENT, default=ENV_PROD): _env_selector(),
        vol.Optional(CONF_NOTIFY_SERVICE, default=DEFAULT_NOTIFY_SERVICE): str,
    }
)


async def _validate(hass, environment: str, nip: str, token: str) -> str | None:
    """Zaloguj się tokenem. Zwraca klucz błędu albo None."""
    api = KsefApi(async_get_clientsession(hass), environment, nip, token.strip())
    try:
        await api.async_validate()
    except KsefAuthError as err:
        _LOGGER.warning("KSeF odrzucił token: %s", err)
        return "invalid_auth"
    except KsefError as err:
        _LOGGER.warning("Błąd połączenia z KSeF: %s", err)
        return "cannot_connect"
    except Exception:  # noqa: BLE001 - np. zły format tokena w szyfrowaniu
        _LOGGER.exception("Nieoczekiwany błąd logowania do KSeF")
        return "unknown"
    await api.async_close()
    return None


class KsefConfigFlow(ConfigFlow, domain=DOMAIN):
    """NIP + token KSeF, sprawdzone próbnym logowaniem."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            nip = _normalize_nip(user_input[CONF_NIP])
            environment = user_input[CONF_ENVIRONMENT]
            token = user_input[CONF_KSEF_TOKEN].strip()
            if not _valid_nip(nip):
                errors[CONF_NIP] = "invalid_nip"
            else:
                await self.async_set_unique_id(f"{environment}_{nip}")
                self._abort_if_unique_id_configured()
                error = await _validate(self.hass, environment, nip, token)
                if error:
                    errors["base"] = error
                else:
                    suffix = "" if environment == ENV_PROD else f" ({environment})"
                    return self.async_create_entry(
                        title=f"KSeF {nip}{suffix}",
                        data={
                            CONF_NIP: nip,
                            CONF_KSEF_TOKEN: token,
                            CONF_ENVIRONMENT: environment,
                        },
                        options={
                            CONF_NOTIFY_SERVICE: user_input.get(
                                CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE
                            ).strip(),
                            CONF_NOTIFY_SALES: False,
                            CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Token unieważniony w Aplikacji Podatnika - prosimy o nowy."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_KSEF_TOKEN].strip()
            error = await _validate(
                self.hass, entry.data[CONF_ENVIRONMENT], entry.data[CONF_NIP], token
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_KSEF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_KSEF_TOKEN): _token_schema()}),
            errors=errors,
            description_placeholders={"nip": entry.data[CONF_NIP]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: KsefConfigEntry) -> OptionsFlow:
        return KsefOptionsFlow()


class KsefOptionsFlow(OptionsFlow):
    """Powiadomienia i częstotliwość odpytywania."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_NOTIFY_SERVICE: (user_input.get(CONF_NOTIFY_SERVICE) or "").strip(),
                    CONF_NOTIFY_SALES: bool(user_input.get(CONF_NOTIFY_SALES)),
                    CONF_SCAN_INTERVAL_MINUTES: int(user_input[CONF_SCAN_INTERVAL_MINUTES]),
                }
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=options.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE),
                ): str,
                vol.Required(
                    CONF_NOTIFY_SALES, default=options.get(CONF_NOTIFY_SALES, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES,
                    default=options.get(
                        CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MINUTES,
                        max=240,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
