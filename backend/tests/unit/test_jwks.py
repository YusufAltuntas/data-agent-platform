"""The JWKS cache refetches on an unknown `kid`, at most once per interval."""

import asyncio
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from dap.api.auth import JwksCache


def _jwk(kid: str) -> dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


class Keycloak:
    def __init__(self) -> None:
        self.keys = [_jwk("k1")]
        self.fetches = 0

    async def fetch(self) -> dict[str, Any]:
        self.fetches += 1
        return {"keys": self.keys}


@pytest.fixture
def keycloak() -> Keycloak:
    return Keycloak()


def test_unknown_kid_triggers_a_refresh(keycloak: Keycloak) -> None:
    cache = JwksCache(keycloak.fetch, min_refresh_interval_s=0)

    async def scenario() -> None:
        assert await cache.get("k1") is not None
        assert await cache.get("k1") is not None
        assert keycloak.fetches == 1

        keycloak.keys = [_jwk("k2")]  # key rotation
        key = await cache.get("k2")
        assert key is not None and key.key_id == "k2"
        assert keycloak.fetches == 2

    asyncio.run(scenario())


def test_refreshes_are_rate_limited(keycloak: Keycloak) -> None:
    cache = JwksCache(keycloak.fetch, min_refresh_interval_s=60)

    async def scenario() -> None:
        assert await cache.get("k1") is not None
        for _ in range(3):
            assert await cache.get("made-up") is None
        assert keycloak.fetches == 1

    asyncio.run(scenario())


def test_concurrent_misses_fetch_once(keycloak: Keycloak) -> None:
    cache = JwksCache(keycloak.fetch, min_refresh_interval_s=0)

    async def scenario() -> None:
        keys = await asyncio.gather(*(cache.get("k1") for _ in range(5)))
        assert all(k is not None for k in keys)
        assert keycloak.fetches == 1

    asyncio.run(scenario())
