from __future__ import annotations

import json
from typing import Any

from keycloak.exceptions import KeycloakError


def ensure_pem_format(public_key: str) -> str:
    key = (public_key or "").strip()
    if key.startswith("-----BEGIN "):
        return key
    return f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----"


def extract_error_detail(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return payload
    else:
        data = payload

    if isinstance(data, dict):
        for key in ("error_description", "error", "message", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(data)
    return str(payload)


def describe_keycloak_exception(exc: KeycloakError) -> str:
    detail = extract_error_detail(getattr(exc, "response_body", None))
    if detail:
        return detail
    message = getattr(exc, "error_message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)
