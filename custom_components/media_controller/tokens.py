"""Minting the access token a panel uses for the REST API.

A panel has no keyboard, so it cannot be told a token; Home Assistant creates
one for it instead. The token belongs to a dedicated non-administrator user,
so it can be revoked on its own and a stolen panel cannot change anything in
Home Assistant beyond what the panel itself does.

This is the one place that touches `hass.auth`. Keeping it in a single module
means a change in that API breaks one file, not the integration.
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.models import RefreshToken, User
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TOKEN_TYPE_LONG_LIVED = "long_lived_access_token"

# Panels are wall-mounted appliances; a token that expires would strand one
# silently. Re-pairing replaces it, and removing the panel revokes it.
TOKEN_LIFETIME = timedelta(days=3650)

USER_NAME_PREFIX = "Media Controller"


def _user_name(panel_name: str) -> str:
    """Return the Home Assistant user name of one panel."""
    return f"{USER_NAME_PREFIX} {panel_name}".strip()


async def _async_panel_user(hass: HomeAssistant, panel_name: str) -> User:
    """Return the dedicated user of one panel, creating it once."""
    name = _user_name(panel_name)
    for user in await hass.auth.async_get_users():
        if user.name == name and not user.system_generated:
            return user
    return await hass.auth.async_create_user(name, group_ids=[GROUP_ID_USER])


async def async_create_panel_token(
    hass: HomeAssistant,
    panel_name: str,
) -> tuple[str, str, str]:
    """Create a long-lived access token for one panel.

    Returns the token, the refresh token ID that revokes it, and the user ID
    that owns it. Both IDs are stored on the config entry so that removing the
    panel can clean up after itself.
    """
    user = await _async_panel_user(hass, panel_name)
    refresh_token = await hass.auth.async_create_refresh_token(
        user,
        client_name=f"{USER_NAME_PREFIX} panel {panel_name}",
        token_type=TOKEN_TYPE_LONG_LIVED,
        access_token_expiration=TOKEN_LIFETIME,
    )
    token = hass.auth.async_create_access_token(refresh_token)
    return token, refresh_token.id, user.id


async def async_revoke_panel_token(
    hass: HomeAssistant,
    user_id: str | None,
    refresh_token_id: str | None,
) -> None:
    """Revoke a panel's token, and its user once nothing else uses it."""
    if not user_id:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        return

    if refresh_token_id:
        token: RefreshToken | None = user.refresh_tokens.get(refresh_token_id)
        if token is not None:
            hass.auth.async_remove_refresh_token(token)

    # The user exists only to own panel tokens. Once the last one is gone it
    # is an empty account in the Home Assistant user list, so remove it.
    if not user.refresh_tokens and user.name.startswith(USER_NAME_PREFIX):
        await hass.auth.async_remove_user(user)
        _LOGGER.debug("Removed the Home Assistant user of a deleted panel")
