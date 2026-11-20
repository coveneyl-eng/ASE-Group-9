"""Secrets come from Azure Key Vault when KEY_VAULT_URL is set (AKS / lowkey-vault emulator), else from env.

In Azure a Key Vault failure stops the service (fail closed). With the local emulator (KEY_VAULT_EMULATOR=1)
a failure falls back to the development value with a warning, so a misbehaving emulator cannot take the
demo down; the dashboard's Key Vault probe uses check() and still reports the real failure.
"""
import logging
import os

from smartcity import config

log = logging.getLogger("secrets")
EMULATOR_API_VERSION = "7.4"  # lowkey-vault rejects the newest API version the Azure SDK defaults to


class _EmulatorCredential:
    """lowkey-vault (local Key Vault emulator) accepts any bearer token."""

    def get_token(self, *scopes, **kwargs):
        from azure.core.credentials import AccessToken
        return AccessToken("emulator", 4_102_444_800)


def _emulator() -> bool:
    return os.getenv("KEY_VAULT_EMULATOR") == "1"


def _client():
    from azure.keyvault.secrets import SecretClient
    if _emulator():
        return SecretClient(config.KEY_VAULT_URL, _EmulatorCredential(), api_version=EMULATOR_API_VERSION,
                            verify_challenge_resource=False, connection_verify=False)
    from azure.identity import DefaultAzureCredential
    return SecretClient(config.KEY_VAULT_URL, DefaultAzureCredential())


def check(name: str, default: str) -> str:
    """Read (seeding the emulator on first run if KEY_VAULT_SEED=1); raises on any failure."""
    client = _client()
    try:
        return client.get_secret(name).value
    except Exception as exc:
        from azure.core.exceptions import ResourceNotFoundError
        if isinstance(exc, ResourceNotFoundError) and os.getenv("KEY_VAULT_SEED") == "1":
            client.set_secret(name, default)  # first local run: seed the emulator with the dev value
            return default
        raise RuntimeError(f"Key Vault secret {name} unavailable: {exc}") from exc


def get_secret(name: str, default: str) -> str:
    if not config.KEY_VAULT_URL:
        return default
    try:
        return check(name, default)
    except Exception as exc:
        if not _emulator():
            raise
        log.warning("Key Vault emulator unavailable (%s); using the development value for %s", exc, name)
        return default
