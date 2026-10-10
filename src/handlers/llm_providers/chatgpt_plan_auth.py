from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Mapping
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import portalocker

from core.app_paths import settings_path
from main_logger import logger


AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
OIDC_CONFIG_URL = "https://auth.openai.com/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
AGENT_NAME = "NeuroMita"
DIRECT_SCOPE = 'chatgpt.tokens.use.direct'
TERMINAL_REFRESH_ERRORS = {
    'invalid_grant', 'invalid_refresh_token', 'token_expired',
    'refresh_token_expired', 'refresh_token_invalidated', 'refresh_token_reused',
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))


def make_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def validate_id_token_claims(
    claims: Mapping[str, Any], *, client_id: str, nonce: str, now: int | None = None
) -> None:
    now = int(time.time()) if now is None else int(now)
    if str(claims.get("iss") or "") != "https://auth.openai.com":
        raise ValueError("Unexpected OpenAI ID token issuer")
    aud = claims.get("aud")
    audiences = [str(x) for x in aud] if isinstance(aud, list) else [str(aud or "")]
    if str(client_id) not in audiences:
        raise ValueError("OpenAI ID token audience mismatch")
    if str(claims.get("nonce") or "") != str(nonce):
        raise ValueError("OpenAI ID token nonce mismatch")
    if int(claims.get("exp") or 0) <= now:
        raise ValueError("OpenAI ID token expired")
    if not str(claims.get("sub") or ""):
        raise ValueError("OpenAI ID token subject is missing")


class ChatGPTPlanAuth:
    """OAuth session manager for the OSS Sign in with ChatGPT flow."""

    def __init__(self, *, client: httpx.Client | None = None, path: Path | None = None) -> None:
        if os.name != 'nt':
            raise RuntimeError('ChatGPT plan authentication currently requires Windows DPAPI')
        self._client = client or httpx.Client(follow_redirects=False, timeout=30.0, trust_env=True)
        self._owns_client = client is None
        self._lock = threading.RLock()
        self._session_depth = 0
        self._usage_states: dict[str, str] = {}
        self._path = path or settings_path("chatgpt_plan_auth.json", create_parent=True)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        try:
            with self._session():
                if not self._data.get("ext_agent_host_id"):
                    self._data["ext_agent_host_id"] = f"urn:uuid:{uuid.uuid4()}"
                    self._save()
        except Exception:
            if self._owns_client:
                self._client.close()
            raise

    @property
    def host_id(self) -> str:
        return str(self._data.get("ext_agent_host_id") or "")

    @contextmanager
    def _session(self):
        with self._lock:
            if self._session_depth:
                yield
                return
            with portalocker.Lock(str(self._path) + '.lock', timeout=300):
                latest = self._load()
                if latest:
                    self._data = latest
                self._session_depth += 1
                try:
                    yield
                finally:
                    self._session_depth -= 1

    def record_inference_error(self, code: str, *, account_id: str | None = None) -> None:
        with self._lock:
            if account_id is None:
                account_id = str((self._data.get('account') or {}).get('client_id') or '')
            if code == 'subscription_sharing_usage_limit_exceeded':
                state = 'quota_exhausted'
            elif code in {'subscription_sharing_usage_unavailable', 'subscription_sharing_user_unavailable'}:
                state = 'temporarily_unavailable'
            elif code in {'chatpass_v2_scope_not_authorized', 'chatpass_v2_invalid_authorization_context',
                          'subscription_sharing_invalid_user', 'chatgpt_plan.http_401', 'chatgpt_plan.http_403'}:
                state = 'session_invalid'
            elif code == 'subscription_sharing_user_not_eligible':
                state = 'not_eligible'
            else:
                state = 'ready' if not code else 'request_failed'
            self._usage_states[account_id] = state

    def status(self) -> dict[str, Any]:
        with self._lock:
            account = self._data.get("account") if isinstance(self._data.get("account"), dict) else {}
            signed_in = bool(account.get('client_id') and (account.get('refresh_token') or account.get('id_token')))
            plan_enabled = signed_in and DIRECT_SCOPE in (account.get('scopes') or [])
            return {
                "signed_in": signed_in,
                'plan_usage_enabled': plan_enabled,
                "email": str(account.get("email") or ""),
                "client_id": str(account.get("client_id") or ""),
                "scopes": list(account.get("scopes") or []),
                'usage_state': self._usage_states.get(str(account.get('client_id') or ''),
                    ('ready' if plan_enabled else 'plan_usage_disabled') if signed_in else 'sign_in_required'),
            }

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._lock:
            active = str((self._data.get('account') or {}).get('client_id') or '')
            return [{'id': key, 'label': f"{record.get('email') or 'ChatGPT'} ({key})",
                     'active': key == active} for key, record in self._data.get('accounts', {}).items()]

    def consume_plan_usage_notice(self) -> bool:
        with self._session():
            if not self.status()['plan_usage_enabled'] or self._data.get('plan_usage_notice_shown'):
                return False
            self._data['plan_usage_notice_shown'] = True
            self._save()
            return True

    def select_account(self, account_id: str) -> dict[str, Any]:
        with self._session():
            record = self._data.get('accounts', {}).get(account_id)
            if not record:
                raise ValueError('Unknown account registration')
            if record.get('refresh_token'):
                previous = self._data.get('account')
                self._data['account'] = dict(record)
                try:
                    if DIRECT_SCOPE in (record.get('scopes') or []):
                        self.get_access_token()
                except Exception:
                    if str((previous or {}).get('client_id') or '') != account_id:
                        self._data['account'] = previous
                        self._save()
                    raise
                self._data['auth_revision'] = int(self._data.get('auth_revision') or 0) + 1
                self._save()
                return self.status()

        return self.sign_in(account_id=account_id)

    def sign_out(self) -> dict[str, Any]:
        with self._session():
            account = dict(self._data.get('account') or {})
            revoked = not bool(account.get('refresh_token'))
            if not revoked:
                try:
                    discovery = self._client.get(OIDC_CONFIG_URL, follow_redirects=False)
                    discovery.raise_for_status()
                    endpoint = str(discovery.json().get('revocation_endpoint') or '')
                    if not endpoint.startswith('https://auth.openai.com/'):
                        raise ValueError('Untrusted revocation endpoint')
                    for attempt in range(3):
                        try:
                            response = self._client.post(endpoint, data={
                                'token': account['refresh_token'], 'token_type_hint': 'refresh_token',
                                'client_id': account['client_id']}, follow_redirects=False)
                        except httpx.HTTPError:
                            if attempt < 2:
                                time.sleep(0.2 * (2 ** attempt))
                            continue
                        if response.status_code == 200:
                            revoked = True
                            break
                        if response.status_code < 500:
                            break
                        time.sleep(0.2 * (2 ** attempt))
                except Exception:
                    revoked = False
            for key in ('access_token', 'refresh_token', 'id_token'):
                account.pop(key, None)
            account['expires_at'] = 0
            self._data['account'] = account
            self._usage_states[str(account.get('client_id') or '')] = 'sign_in_required'
            self._data['auth_revision'] = int(self._data.get('auth_revision') or 0) + 1
            self._save()
            return {'revoked': revoked, **self.status()}

    def sign_in(self, timeout: float = 1800.0, *, new_account: bool = False, account_id: str = '') -> dict[str, Any]:
        with self._session():
            account = {} if new_account else dict(
                self._data.get('accounts', {}).get(account_id, {}) if account_id else self._data.get('account') or {})
            if account_id and not account:
                raise ValueError('Unknown account registration')
            expected_revision = int(self._data.get('auth_revision') or 0)
            host_id = self.host_id
        saved_client_id = str(account.get("client_id") or "")
        client_id = saved_client_id or DYNAMIC_CLIENT_ID
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        callback: dict[str, str] = {}
        event = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                values = parse_qs(parsed.query)
                for key in ("code", "state", "client_id", "scope", "error", "error_description"):
                    if values.get(key):
                        callback[key] = str(values[key][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<html><body><h2>NeuroMita</h2><p>Authorization received. You can close this tab.</p></body></html>".encode("utf-8")
                )
                event.set()

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = int(server.server_address[1])
        redirect_uri = f"http://127.0.0.1:{port}/auth/callback"
        thread = threading.Thread(target=server.serve_forever, name="chatgpt-plan-oauth", daemon=True)
        thread.start()

        params = {
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if not saved_client_id:
            params["agent_name_hint"] = AGENT_NAME
        else:
            if DIRECT_SCOPE not in (account.get('scopes') or []):
                params['prompt'] = 'consent'
            id_token_hint = str(account.get("id_token") or "")
            email = str(account.get("email") or "")
            if id_token_hint:
                params["id_token_hint"] = id_token_hint
            if email:
                params["login_hint"] = email

        auth_url = AUTHORIZE_URL + "?" + urlencode(params)
        try:
            if not webbrowser.open(auth_url, new=1, autoraise=True):
                logger.warning("Could not open the system browser for Sign in with ChatGPT")
            if not event.wait(max(1.0, float(timeout))):
                raise TimeoutError("Sign in with ChatGPT timed out")
        finally:
            server.shutdown()
            server.server_close()

        if callback.get("state") != state:
            raise ValueError("Sign in with ChatGPT returned an invalid state")
        if callback.get("error"):
            raise RuntimeError(callback.get("error_description") or callback["error"])
        code = str(callback.get("code") or "")
        if not code:
            raise RuntimeError("Sign in with ChatGPT did not return an authorization code")

        returned_client_id = str(callback.get("client_id") or "")
        if saved_client_id:
            if returned_client_id and returned_client_id != saved_client_id:
                raise ValueError("Sign in with ChatGPT returned a different client registration")
            issued_client_id = saved_client_id
        else:
            issued_client_id = returned_client_id
            if not issued_client_id or issued_client_id == DYNAMIC_CLIENT_ID:
                raise RuntimeError("ChatGPT client registration was not completed")

        token_response = self._client.post(
            TOKEN_URL,
            follow_redirects=False,
            data={
                "grant_type": "authorization_code",
                "client_id": issued_client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": RESOURCE,
            },
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        record = self._validated_record(tokens, issued_client_id, nonce)
        previous_subject = str(account.get("subject") or "")
        if previous_subject and str(record.get("subject") or "") != previous_subject:
            raise ValueError("Sign in with ChatGPT returned a different account identity")
        with self._session():
            if int(self._data.get('auth_revision') or 0) != expected_revision or self.host_id != host_id:
                raise RuntimeError('ChatGPT account state changed while signing in; start sign-in again')
            current = self._data.get('accounts', {}).get(issued_client_id, {})
            if saved_client_id:
                if not current or any(current.get(key) != account.get(key) for key in ('client_id', 'subject', 'issuer')):
                    raise RuntimeError('ChatGPT account registration changed while signing in')
            elif current:
                raise RuntimeError('ChatGPT account registration changed while signing in')
            self._data['account'] = record
            self._data['auth_revision'] = expected_revision + 1
            self._usage_states[issued_client_id] = (
                'ready' if DIRECT_SCOPE in record['scopes'] else 'plan_usage_disabled')
            self._save()
            return self.status()

    def get_access_token(self) -> str:
        with self._session():
            account = self._data.get("account") if isinstance(self._data.get("account"), dict) else {}
            if not account.get('client_id') or not (account.get('access_token') or account.get('refresh_token')):
                raise RuntimeError("Sign in with ChatGPT is required")
            if DIRECT_SCOPE not in (account.get('scopes') or []):
                raise PermissionError('Sign in with ChatGPT again to enable ChatGPT plan usage')
            access_token = str(account.get("access_token") or "")
            expires_at = int(account.get("expires_at") or 0)
            if access_token and expires_at > int(time.time()) + 90:
                return access_token
            if not account.get("refresh_token") or not account.get("client_id"):
                raise RuntimeError("Sign in with ChatGPT is required")
            self._refresh(account)
            if DIRECT_SCOPE not in (self._data['account'].get('scopes') or []):
                raise PermissionError('Sign in with ChatGPT again to enable ChatGPT plan usage')
            return str(self._data["account"].get("access_token") or "")

    def get_credentials(self) -> tuple[str, str]:
        with self._session():
            token = self.get_access_token()
            return token, str(self._data['account']['client_id'])

    def list_models(self) -> list[dict[str, str]]:
        token = self.get_access_token()
        response = self._client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        models = data.get("models") if isinstance(data, dict) else []
        result: list[dict[str, str]] = []
        for item in models or []:
            if not isinstance(item, dict) or item.get("visibility") != "list":
                continue
            slug = str(item.get("slug") or "").strip()
            if slug:
                result.append({"id": slug, "name": str(item.get("display_name") or slug)})
        return result

    def _refresh(self, account: dict[str, Any]) -> None:
        response = self._client.post(
            TOKEN_URL,
            follow_redirects=False,
            data={
                "grant_type": "refresh_token",
                "client_id": str(account.get("client_id") or ""),
                "refresh_token": str(account.get("refresh_token") or ""),
                "resource": RESOURCE,
            },
        )
        if response.status_code in {400, 401, 403}:
            try:
                error = response.json().get('error')
                code = str(error.get('code') or error.get('type') or '') if isinstance(error, dict) else str(error or '')
            except (ValueError, AttributeError):
                code = ''
            if code in TERMINAL_REFRESH_ERRORS:
                for key in ('access_token', 'refresh_token', 'id_token'):
                    account.pop(key, None)
                account['expires_at'] = 0
                self._data['account'] = account
                self._usage_states[str(account.get('client_id') or '')] = 'sign_in_required'
                self._save()
                raise RuntimeError('Sign in with ChatGPT is required; the saved session is no longer valid')
        response.raise_for_status()
        payload = response.json()
        if not payload.get('access_token'):
            raise ValueError('OpenAI refresh response did not include an access token')
        account["access_token"] = str(payload.get("access_token") or "")
        if payload.get("refresh_token"):
            account["refresh_token"] = str(payload["refresh_token"])
        if payload.get("id_token"):
            account["id_token"] = str(payload["id_token"])
        account["expires_at"] = int(time.time()) + int(payload.get("expires_in") or 3600)
        if 'scope' in payload:
            account['scopes'] = str(payload.get('scope') or '').split()
        self._usage_states[str(account.get('client_id') or '')] = (
            'ready' if DIRECT_SCOPE in (account.get('scopes') or []) else 'plan_usage_disabled')
        self._data["account"] = account
        self._save()

    def _validated_record(self, tokens: Mapping[str, Any], client_id: str, nonce: str) -> dict[str, Any]:
        id_token = str(tokens.get("id_token") or "")
        if not id_token:
            raise ValueError("OpenAI token response did not include an ID token")
        claims = self._validate_jwt(id_token, client_id=client_id, nonce=nonce)
        scopes = str(tokens.get("scope") or "").split()
        return {
            "email": str(claims.get("email") or ""),
            "issuer": str(claims.get("iss") or ""),
            "subject": str(claims.get("sub") or ""),
            "client_id": client_id,
            "ext_agent_host_id": self.host_id,
            "id_token": id_token,
            "access_token": str(tokens.get("access_token") or ""),
            "refresh_token": str(tokens.get("refresh_token") or ""),
            "token_type": str(tokens.get("token_type") or "Bearer"),
            "expires_at": int(time.time()) + int(tokens.get("expires_in") or 3600),
            "scopes": scopes,
        }

    def _validate_jwt(self, token: str, *, client_id: str, nonce: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid OpenAI ID token")
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        claims = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        if str(header.get("alg") or "") != "RS256":
            raise ValueError("Unsupported OpenAI ID token algorithm")

        discovery = self._client.get(OIDC_CONFIG_URL)
        discovery.raise_for_status()
        jwks_uri = str(discovery.json().get("jwks_uri") or "")
        if not jwks_uri:
            raise ValueError("OpenAI OIDC configuration has no JWKS URI")
        jwks_response = self._client.get(jwks_uri)
        jwks_response.raise_for_status()
        keys = jwks_response.json().get("keys") or []
        key = next((item for item in keys if isinstance(item, dict) and item.get("kid") == header.get("kid")), None)
        if not key:
            raise ValueError("OpenAI ID token signing key was not found")

        from Crypto.Hash import SHA256
        from Crypto.PublicKey import RSA
        from Crypto.Signature import pkcs1_15

        n = int.from_bytes(_b64url_decode(str(key.get("n") or "")), "big")
        e = int.from_bytes(_b64url_decode(str(key.get("e") or "")), "big")
        public_key = RSA.construct((n, e))
        digest = SHA256.new(f"{parts[0]}.{parts[1]}".encode("ascii"))
        try:
            pkcs1_15.new(public_key).verify(digest, _b64url_decode(parts[2]))
        except (ValueError, TypeError) as exc:
            raise ValueError("OpenAI ID token signature verification failed") from exc

        validate_id_token_claims(claims, client_id=client_id, nonce=nonce)
        return claims

    def _load(self) -> dict[str, Any]:
        try:
            path = Path(self._path)
            if not path.exists():
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError('Invalid credential envelope')
            if 'account' in payload or 'accounts' in payload:
                raise ValueError('Unprotected credential record')
            if payload.get('protected_accounts'):
                records = self._unprotect_json(str(payload.pop('protected_accounts')))
                payload['accounts'] = records
                payload['account'] = dict(records.get(str(payload.get('active_account') or ''), {}))
            elif payload.get("protected_account"):
                payload["account"] = self._unprotect_json(str(payload.pop("protected_account")))
                record = payload['account']
                payload['accounts'] = {record['client_id']: dict(record)}
            return payload
        except Exception as exc:
            raise RuntimeError('Could not open protected ChatGPT plan credentials') from exc

    def _save(self) -> None:
        path = Path(self._path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ext_agent_host_id": self._data.get("ext_agent_host_id", ""),
                   'plan_usage_notice_shown': bool(self._data.get('plan_usage_notice_shown')),
                   'auth_revision': int(self._data.get('auth_revision') or 0)}
        account = self._data.get("account")
        if isinstance(account, dict) and account:
            records = self._data.setdefault('accounts', {})
            records[account['client_id']] = dict(account)
            payload['active_account'] = account['client_id']
            payload['protected_accounts'] = self._protect_json(records)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    @staticmethod
    def _protect_json(value: Mapping[str, Any]) -> str:
        raw = json.dumps(dict(value), ensure_ascii=False).encode("utf-8")
        if os.name == "nt":
            import win32crypt
            encrypted = win32crypt.CryptProtectData(raw, "NeuroMita ChatGPT Plan", None, None, None, 0)
            return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
        raise RuntimeError('ChatGPT plan protected credential storage currently requires Windows DPAPI')

    @staticmethod
    def _unprotect_json(value: str) -> dict[str, Any]:
        mode, _, encoded = str(value).partition(":")
        if mode != 'dpapi':
            raise RuntimeError('Unsupported unprotected credential envelope; sign in again using protected storage')
        raw = base64.b64decode(encoded.encode("ascii"))
        if mode == "dpapi":
            if os.name != "nt":
                raise RuntimeError("Windows DPAPI credentials cannot be opened on this platform")
            import win32crypt
            raw = win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1]
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


_default_auth: ChatGPTPlanAuth | None = None
_default_lock = threading.Lock()


def get_chatgpt_plan_auth() -> ChatGPTPlanAuth:
    global _default_auth
    with _default_lock:
        if _default_auth is None:
            _default_auth = ChatGPTPlanAuth()
        return _default_auth


__all__ = [
    "ChatGPTPlanAuth", "get_chatgpt_plan_auth", "make_pkce_pair", "validate_id_token_claims",
]
