"""Shared RS256 test keys and JWT helpers for OIDC-style auth tests."""

import os
import time
from unittest.mock import AsyncMock, patch

from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)
_priv_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
_pub_pem = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
_test_private = JsonWebKey.import_key(
    _priv_pem, {"use": "sig", "kid": "test-key-1"}
)
_test_public = JsonWebKey.import_key(
    _pub_pem, {"use": "sig", "kid": "test-key-1"}
)
_test_key_set = JsonWebKey.import_key_set({"keys": [_test_public.as_dict()]})


def make_access_token(
    *,
    sub: str = "abc-123-uuid",
    email: str = "user@example.com",
    expired: bool = False,
) -> str:
    now = int(time.time())
    iss = os.environ["AUTHENTIK_ISSUER"]
    payload = {
        "sub": sub,
        "email": email,
        "iss": iss,
        "exp": now - 1 if expired else now + 3600,
        "iat": now,
    }
    raw = jwt.encode(
        {"alg": "RS256", "kid": "test-key-1"}, payload, _test_private
    )
    return raw.decode() if isinstance(raw, bytes) else raw


def mock_jwks():
    return patch("app.auth._get_jwks", new=AsyncMock(return_value=_test_key_set))
