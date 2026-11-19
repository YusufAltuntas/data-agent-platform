"""Fernet helpers round-trip secrets and reject tokens made with another key."""

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from dap import crypto
from dap.settings import Settings


def _settings(key: bytes) -> Settings:
    return Settings(
        postgres_password=SecretStr("x"),
        ds_sales_ro_password=SecretStr("x"),
        ds_hr_ro_password=SecretStr("x"),
        dap_fernet_key=SecretStr(key.decode()),
        rabbitmq_password=SecretStr("x"),
        litellm_master_key=SecretStr("x"),
    )


def test_encrypt_round_trip() -> None:
    settings = _settings(Fernet.generate_key())
    token = crypto.encrypt(settings, "sk-team-key")
    assert token != "sk-team-key"
    assert crypto.decrypt(settings, token) == "sk-team-key"


def test_decrypt_rejects_other_key() -> None:
    token = crypto.encrypt(_settings(Fernet.generate_key()), "sk-team-key")
    with pytest.raises(InvalidToken):
        crypto.decrypt(_settings(Fernet.generate_key()), token)
