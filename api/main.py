"""Small, single-worker contact service. nginx is the only public entry point."""
from collections import OrderedDict, deque
from dataclasses import dataclass
from email.message import EmailMessage
from ipaddress import ip_address, ip_network
import logging
import os
import smtplib
import ssl
from threading import Lock
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

logger = logging.getLogger("contact")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Contact(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr = Field(max_length=254)
    message: str = Field(min_length=10, max_length=5000)

    @field_validator("name", "email")
    @classmethod
    def no_header_controls(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Control characters are not allowed")
        return value


class RateLimiter:
    """Bounded in-memory sliding window; one worker, resets on restart."""
    def __init__(self, limit: int = 5, window: int = 900, max_ips: int = 10000):
        self.limit = limit
        self.window = window
        self.max_ips = max_ips
        self.entries: OrderedDict[str, deque] = OrderedDict()
        self.lock = Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            # Entries are ordered by most recent accepted request.
            while self.entries:
                oldest = next(iter(self.entries))
                if self.entries[oldest][-1] > now - self.window:
                    break
                self.entries.popitem(last=False)
            attempts = self.entries.get(key)
            if attempts is None:
                # Refuse new keys at capacity rather than evict active limits.
                if len(self.entries) >= self.max_ips:
                    return False, self.window
                attempts = deque()
                self.entries[key] = attempts
            while attempts and attempts[0] <= now - self.window:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False, max(1, int(self.window - (now - attempts[0])) + 1)
            attempts.append(now)
            self.entries.move_to_end(key)
            return True, 0


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    # Only trust a configured proxy peer, never arbitrary forwarded headers.
    # Compose assigns nginx a fixed private IP; direct local runs trust no proxy.
    trusted = os.getenv("TRUSTED_PROXY_CIDR", "")
    if trusted:
        try:
            if ip_address(peer) in ip_network(trusted):
                return str(ip_address(request.headers.get("x-real-ip", peer)))
        except ValueError:
            pass
    return peer


@app.middleware("http")
async def limit_contact(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/api/contact":
        allowed, retry_after = limiter.allow(client_ip(request))
        if not allowed:
            return JSONResponse({"detail": "rate_limited"}, status_code=429,
                                headers={"Retry-After": str(retry_after)})
        # nginx caps bodies too. This protects direct local development requests.
        body = await request.body()
        if len(body) > 32768:
            return JSONResponse({"detail": "request_too_large"}, status_code=413)
    return await call_next(request)


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipient: str
    security: str

    @classmethod
    def from_env(cls):
        security = os.getenv("SMTP_SECURITY", "starttls")
        if security not in {"starttls", "ssl"}:
            raise ValueError("SMTP_SECURITY must be starttls or ssl")
        settings = cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587")),
            user=os.environ["SMTP_USER"],
            password=os.environ["SMTP_PASSWORD"],
            sender=os.environ["SMTP_FROM"],
            recipient=os.getenv("SMTP_TO", "araodaniel14@gmail.com"),
            security=security,
        )
        if not all([settings.host, settings.user, settings.password, settings.sender, settings.recipient]):
            raise ValueError("SMTP configuration is incomplete")
        if not 1 <= settings.port <= 65535:
            raise ValueError("Invalid SMTP port")
        return settings


def send_email(contact: Contact) -> None:
    settings = SMTPSettings.from_env()
    message = EmailMessage()
    message["Subject"] = "Website project inquiry"
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message["Reply-To"] = str(contact.email)
    message.set_content(f"Name: {contact.name}\nEmail: {contact.email}\n\n{contact.message}")
    context = ssl.create_default_context()
    if settings.security == "ssl":
        transport = smtplib.SMTP_SSL(settings.host, settings.port, timeout=10, context=context)
    else:
        transport = smtplib.SMTP(settings.host, settings.port, timeout=10)
    with transport as smtp:
        if settings.security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(settings.user, settings.password)
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


@app.get("/api/health")
def health():
    # Liveness only: does not assert SMTP readiness or expose configuration.
    return {"status": "ok"}


@app.post("/api/contact")
def contact(payload: Contact):
    # Sync handler runs in FastAPI's thread pool; SMTP does not block the event loop.
    try:
        send_email(payload)
    except Exception as exc:
        logger.warning("Contact delivery failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="delivery_unavailable") from None
    return {"status": "sent"}
