"""Bearer JWT validation against Keycloak's JWKS (design §7, K7, K8)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

AUDIENCE = "dap-api"
PLATFORM_ADMIN_ROLE = "platform-admin"
ALGORITHMS = ["RS256"]

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


class AuthError(Exception):
    """The token is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class Identity:
    email: str
    platform_admin: bool


def http_jwks_fetcher(client: httpx.AsyncClient, url: str) -> JwksFetcher:
    async def fetch() -> dict[str, Any]:
        response = await client.get(url)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    return fetch


class JwksCache:
    """Signing keys by `kid`. Fetched on first use and again when an unknown `kid` arrives.

    Refetches are at most one per `min_refresh_interval_s`, so tokens with made-up `kid`s
    cannot turn every request into a JWKS request.
    """

    def __init__(self, fetch: JwksFetcher, *, min_refresh_interval_s: float = 10.0) -> None:
        self._fetch = fetch
        self._min_refresh_interval_s = min_refresh_interval_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK | None:
        if kid not in self._keys:
            async with self._lock:
                if kid not in self._keys and self._may_refresh():
                    await self._refresh()
        return self._keys.get(kid)

    def _may_refresh(self) -> bool:
        return (
            self._fetched_at is None
            or time.monotonic() - self._fetched_at >= self._min_refresh_interval_s
        )

    async def _refresh(self) -> None:
        self._fetched_at = time.monotonic()
        jwks = jwt.PyJWKSet.from_dict(await self._fetch())
        self._keys = {key.key_id: key for key in jwks.keys if key.key_id}


class TokenVerifier:
    def __init__(self, jwks: JwksCache, *, issuer: str) -> None:
        self._jwks = jwks
        self._issuer = issuer

    async def verify(self, token: str) -> Identity:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = await self._jwks.get(kid) if isinstance(kid, str) else None
            if key is None:
                raise AuthError("unknown signing key")
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as e:
            raise AuthError(str(e)) from e

        # K8: membership is keyed by e-mail, so only a verified e-mail is trusted.
        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str) or not email:
            raise AuthError("no verified e-mail")
        roles = (claims.get("realm_access") or {}).get("roles") or []
        return Identity(email=email.lower(), platform_admin=PLATFORM_ADMIN_ROLE in roles)
