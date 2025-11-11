"""Shared authentication models that are provider agnostic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity information extracted from a validated access token."""

    subject: str
    issuer: str
    token: str
    username: Optional[str]
    email: Optional[str]
    audience: Set[str]
    scope: Set[str]
    roles: Set[str]
    claims: Dict[str, Any]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scope

    def has_role(self, role: str) -> bool:
        return role in self.roles
