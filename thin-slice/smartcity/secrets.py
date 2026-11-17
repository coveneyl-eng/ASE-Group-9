"""Secrets come from Azure Key Vault when KEY_VAULT_URL is set (AKS / lowkey-vault emulator), else from env."""
import os

from smartcity import config


class _EmulatorCredential:
    """lowkey-vault (local Key Vault emulator) accepts any bearer token."""

    def get_token(self, *scopes, **kwargs):
        from azure.core.credentials import AccessToken
        return AccessToken("emulator", 4_102_444_800)


def get_secret(name: str, default: str) -> str:
    if not config.KEY_VAULT_URL:
        return default
    from azure.keyvault.secrets import SecretClient
    if os.getenv("KEY_VAULT_EMULATOR") == "1":
        client = SecretClient(config.KEY_VAULT_URL, _EmulatorCredential(), verify_challenge_resource=False,
                              connection_verify=False)
    else:
        from azure.identity import DefaultAzureCredential
        client = SecretClient(config.KEY_VAULT_URL, DefaultAzureCredential())
    try:
        return client.get_secret(name).value
    except Exception as exc:
        if os.getenv("KEY_VAULT_SEED") == "1":  # first local run: seed the emulator with the dev value
            client.set_secret(name, default)
            return default
        raise RuntimeError(f"Key Vault secret {name} unavailable: {exc}") from exc
