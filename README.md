# Daniel Arao — personal landing page

A bilingual, static HTML/CSS/JavaScript page with a small FastAPI SMTP service. No frontend framework or build step. The original profile photo is included in `assets/` and framed with CSS.

## Run

```sh
cp .env.example .env
# Edit .env with your SMTP credentials and listener port.
docker compose up --build -d
```

Open `http://localhost:8080` (or the configured `HTTP_PORT`). nginx serves the page and forwards `/api/` to the private API container. The API has no published port. Static pages remain available if the API is unavailable. Do not use `python -m http.server` for production: it exposes the project directory rather than the curated public image.

For a local static preview only:

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

The contact form offers a prefilled email draft when the static preview has no API. With JavaScript disabled, the full English content and direct email link remain usable; the JSON contact flow requires JavaScript.

## Configure before publishing

- Replace every `https://example.com` in `index.html` with the public HTTPS origin (canonical, Open Graph, Twitter image, JSON-LD). Comments mark these locations. The original local portrait is the social image.
- Fill `.env`; never commit it. `SMTP_FROM` must be a sender permitted by the provider. `SMTP_TO` defaults to `araodaniel14@gmail.com`. Use `SMTP_SECURITY=starttls` with port 587 or `ssl` with port 465. Both verify TLS certificates. Use a provider/app password where required.
- Put HTTPS termination in front of nginx on the VPS. The supplied container serves HTTP; certificate provisioning depends on your domain. If binding behind a host reverse proxy, change the published port to `127.0.0.1:8080:80`.
- If another reverse proxy sits ahead of nginx, configure `set_real_ip_from` for **only that proxy's actual address/CIDR** and `real_ip_header X-Forwarded-For` in nginx. Do not trust all addresses. Without this step, the rate limit may group visitors under the proxy's IP.
- Compose reserves `172.30.14.0/24`, with nginx at `172.30.14.2`. If the subnet conflicts with your VPS network, change the subnet, nginx address and API `TRUSTED_PROXY_CIDR` together.
- Review the supplied Upwork figures and the specialization's “in progress” status when updating the page. Project support and NDA terms are agreed per project; there is no fixed support duration advertised.

The server's API docs are disabled. `/api/health` reports process liveness, not SMTP readiness. For production validation, send one controlled form message after configuring SMTP and confirm receipt in the target mailbox.

## Contact contract

`POST /api/contact`, `Content-Type: application/json`:

```json
{"name":"Jane Doe","email":"jane@example.com","message":"I need clinic data in CSV format."}
```

Name: 2–100 characters; valid email: at most 254 characters; message: 10–5000 characters. Outer whitespace is removed. Extra fields and header control characters are rejected. nginx caps request bodies at 32 KiB.

- `200 {"status":"sent"}`: SMTP accepted the email. This is not a guarantee of inbox placement.
- `422`: invalid input.
- `429`: five attempts per IP in a rolling 15-minute window exceeded; includes `Retry-After`.
- `503`: SMTP configuration or delivery unavailable.

The frontend retains inputs after failure, offers a prefilled `mailto:` link for unavailable/unconfirmed delivery and reports validation and rate-limit errors separately. It does not automatically resend. An email draft requires a configured mail application; the direct address is always visible. A network timeout can happen after SMTP acceptance, so the fallback message asks visitors to check before sending again.

Rate limiting uses bounded process memory (10,000 active IPs) with a lock and expiration cleanup. Run **one API worker and one API replica**. Restarting clears the limits. If scaling, replace it with a shared limiter. API trusts `X-Real-IP` only from the configured nginx peer; nginx overwrites incoming forwarding headers. Logs omit message bodies, email addresses and SMTP exception details. No database or analytics service is used.

## Content and design

- English HTML is the baseline. `main.js` contains both language versions. Update the English HTML and both dictionary entries when changing copy; keep metadata in sync too. Language preference uses `daniel-arao-language` in localStorage and defaults to English.
- CSS tokens: drawing paper `#E9EEF0`, reading surface `#F5F7F8`, graphite `#23343D`, steel `#52636D`, rules `#A7B4BC`, signal `#005FCC`.
- Barlow Semi Condensed 400/500/600 for prose and headings; IBM Plex Mono 400 for technical data. Google Fonts is the only external frontend dependency. System fallbacks keep all content readable if fonts fail.
- The layout borrows alignment and information hierarchy from instrument data sheets. No simulated plant status, client logos, invented metrics or decorative diagrams.
- One hero line animation; no scroll-triggered entrances. Reduced motion removes it and smooth scrolling.

## Checks

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pytest httpx
python -m pytest -q
node --check main.js
docker compose config --quiet
```

For browser checks, install Playwright as a development tool (`pip install playwright` and `playwright install chromium`), start the local preview, then run `python tests/browser_check.py`. Set `BASE_URL` to test the nginx container instead. The script checks both languages at five widths, persistence, form states, reduced motion and no-JavaScript content.

API tests mock SMTP: they cover validation, delivery failure, TLS/Reply-To handling, proxy trust, rate limits and expiry. They do not send email.

For operation:

```sh
docker compose ps
docker compose logs --tail=100 web api
curl http://localhost:8080/api/health
```

Rebuild after editing static files or Python code: `docker compose up --build -d`. SMTP configuration changes require recreating the API container. To stop the stack: `docker compose down`.
