"""Symmetric encryption of stored secrets (e.g. `teams.llm_key_enc`) with `DAP_FERNET_KEY`."""

from cryptography.fernet import Fernet

from dap.settings import Settings


def _fernet(settings: Settings) -> Fernet:
    return Fernet(settings.dap_fernet_key.get_secret_value())


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    """Raises `cryptography.fernet.InvalidToken` if the token was not made with this key."""
    return _fernet(settings).decrypt(token.encode()).decode()
