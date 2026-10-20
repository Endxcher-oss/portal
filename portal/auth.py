# Capability token and session cookie: one token per run, one cookie per host.

import base64
import hashlib
import hmac
import secrets
import time

COOKIE_NAME = "portal_session"
SESSION_TTL = 30 * 24 * 3600


class Auth:
    def __init__(self, token=None):
        self.token = token or secrets.token_urlsafe(24)
        self.secret = secrets.token_bytes(32)

    def matches(self, supplied):
        return hmac.compare_digest(str(supplied).encode(), self.token.encode())

    def cookie(self, secure):
        expires = int(time.time()) + SESSION_TTL
        value = f"{expires}.{self._sign(str(expires))}"
        flag = "; Secure" if secure else ""
        return f"{COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Lax{flag}; Max-Age={SESSION_TTL}"

    def authorized(self, request):
        return self._valid(request.cookies.get(COOKIE_NAME))

    def _sign(self, text):
        digest = hmac.new(self.secret, text.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def _valid(self, raw):
        if not raw or "." not in raw:
            return False
        expires, _, signature = raw.partition(".")
        if not expires.isdigit() or int(expires) < time.time():
            return False
        return hmac.compare_digest(signature, self._sign(expires))
