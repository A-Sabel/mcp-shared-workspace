"""Small persistent OAuth provider for Claude's remote MCP connector.

The existing MCP_TOKEN is the owner credential shown on the local sign-in page.
OAuth access and refresh tokens are random, short-lived, and stored by digest.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class WorkspaceOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """OAuth authorization-code + PKCE provider with SQLite persistence."""

    def __init__(self, *, db_path: Path, owner_token: str, resource: str) -> None:
        self.db_path = db_path
        self.owner_token = owner_token
        self.resource = resource
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_codes (
                    code_hash TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    data TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS oauth_logins (
                    tx_id TEXT PRIMARY KEY, data TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._connect() as db:
            row = db.execute("SELECT data FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row["data"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # DCR clients are public PKCE clients; never issue a client secret.
        client_info.client_secret = None
        client_info.token_endpoint_auth_method = "none"
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO oauth_clients(client_id,data) VALUES(?,?)",
                (client_info.client_id, client_info.model_dump_json()),
            )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") != self.resource.rstrip("/"):
            raise AuthorizeError("invalid_target", "Unknown MCP resource")
        tx_id = secrets.token_urlsafe(32)
        payload = {
            "client_id": client.client_id,
            "state": params.state,
            "scopes": params.scopes or ["workspace"],
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource or self.resource,
        }
        with self._connect() as db:
            db.execute("DELETE FROM oauth_logins WHERE expires_at < ?", (int(time.time()),))
            db.execute(
                "INSERT INTO oauth_logins(tx_id,data,expires_at) VALUES(?,?,?)",
                (tx_id, json.dumps(payload), int(time.time()) + 600),
            )
        return f"/oauth-login?{urlencode({'tx': tx_id})}"

    async def complete_login(self, tx_id: str, supplied_secret: str) -> str | None:
        if not hmac.compare_digest(supplied_secret.encode(), self.owner_token.encode()):
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT data FROM oauth_logins WHERE tx_id=? AND expires_at>=?",
                (tx_id, int(time.time())),
            ).fetchone()
            if not row:
                return None
            db.execute("DELETE FROM oauth_logins WHERE tx_id=?", (tx_id,))
            data = json.loads(row["data"])
            code = secrets.token_urlsafe(32)
            code_data = {
                "scopes": data["scopes"],
                "expires_at": int(time.time()) + 300,
                "client_id": data["client_id"],
                "code_challenge": data["code_challenge"],
                "redirect_uri": data["redirect_uri"],
                "redirect_uri_provided_explicitly": data["redirect_uri_provided_explicitly"],
                "resource": data["resource"],
                "subject": "workspace-owner",
            }
            db.execute(
                "INSERT INTO oauth_codes(code_hash,data) VALUES(?,?)",
                (_digest(code), json.dumps(code_data)),
            )
        return construct_redirect_uri(data["redirect_uri"], code=code, state=data["state"])

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self._connect() as db:
            row = db.execute("SELECT data FROM oauth_codes WHERE code_hash=?", (_digest(authorization_code),)).fetchone()
        if not row:
            return None
        code = AuthorizationCode.model_validate({**json.loads(row["data"]), "code": authorization_code})
        return code if code.client_id == client.client_id and code.expires_at >= time.time() else None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self._connect() as db:
            deleted = db.execute("DELETE FROM oauth_codes WHERE code_hash=?", (_digest(authorization_code.code),))
            if deleted.rowcount != 1:
                raise TokenError("invalid_grant", "Authorization code was already used")
        return self._issue(
            client.client_id,
            authorization_code.scopes,
            authorization_code.resource,
            subject=authorization_code.subject or "workspace-owner",
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT data FROM oauth_tokens WHERE token_hash=? AND kind='refresh' AND revoked=0",
                (_digest(refresh_token),),
            ).fetchone()
        if not row:
            return None
        token = RefreshToken.model_validate({**json.loads(row["data"]), "token": refresh_token})
        return token if token.client_id == client.client_id and (token.expires_at is None or token.expires_at >= time.time()) else None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        with self._connect() as db:
            db.execute("UPDATE oauth_tokens SET revoked=1 WHERE token_hash=?", (_digest(refresh_token.token),))
        return self._issue(
            client.client_id,
            scopes or refresh_token.scopes,
            refresh_token.resource,
            subject=refresh_token.subject or "workspace-owner",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT data FROM oauth_tokens WHERE token_hash=? AND kind='access' AND revoked=0",
                (_digest(token),),
            ).fetchone()
        if not row:
            return None
        access = AccessToken.model_validate({**json.loads(row["data"]), "token": token})
        return access if access.expires_at is None or access.expires_at >= time.time() else None

    async def verify_token(self, token: str) -> AccessToken | None:
        """TokenVerifier interface used by the MCP bearer middleware."""
        access = await self.load_access_token(token)
        if access:
            return access
        # Preserve the existing shared bearer-token client path during migration.
        if hmac.compare_digest(token.encode(), self.owner_token.encode()):
            return AccessToken(
                token=token,
                client_id="legacy-workspace-client",
                scopes=["workspace"],
                resource=self.resource,
                subject="workspace-owner",
            )
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._connect() as db:
            db.execute("UPDATE oauth_tokens SET revoked=1 WHERE token_hash=?", (_digest(token.token),))

    def _issue(
        self,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        *,
        subject: str = "workspace-owner",
    ) -> OAuthToken:
        now = int(time.time())
        access_value = secrets.token_urlsafe(40)
        refresh_value = secrets.token_urlsafe(40)
        access = AccessToken(
            token=access_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + 3600,
            resource=resource or self.resource,
            subject=subject,
        )
        refresh = RefreshToken(
            token=refresh_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + 30 * 24 * 3600,
            resource=resource or self.resource,
            subject=subject,
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO oauth_tokens(token_hash,kind,data) VALUES(?,?,?)",
                (_digest(access_value), "access", access.model_dump_json(exclude={"token"})),
            )
            db.execute(
                "INSERT INTO oauth_tokens(token_hash,kind,data) VALUES(?,?,?)",
                (_digest(refresh_value), "refresh", refresh.model_dump_json(exclude={"token"})),
            )
        return OAuthToken(
            access_token=access_value,
            expires_in=3600,
            refresh_token=refresh_value,
            scope=" ".join(scopes),
        )
