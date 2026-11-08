# Deployment secrets and configuration

The Compose profile is fail-closed: it requires exact HTTPS browser origins and three distinct bearer secrets before starting the services. Keep the deployment `.env` outside the repository, restrict it to the deployment account (`chmod 600`), and do not attach it to CI artifacts or paste its contents into logs.

## Required values

| Variable | Used by | Guidance |
| --- | --- | --- |
| `SWING_ALLOWED_ORIGINS` | Twin and Agent | Comma-separated exact HTTPS origins, such as `https://swing.example.org`; no paths, wildcard, or trailing slash. |
| `SWING_OPERATOR_TOKEN` | Agent | Generate a random, high-entropy bearer token. The current browser UI has no login/token-entry flow, so authenticated browser mutations are unavailable; use a separately authenticated API client until that UI exists. |
| `SWING_ADMIN_TOKEN` | Twin | Separate random secret for direct Twin administrative mutations. Never expose it to a browser or the Agent. |
| `SWING_INTERNAL_TWIN_TOKEN` | Agent and Twin | A third random secret used only by the Agent's server-side Twin mutation calls. |
| `GOOGLE_API_KEY` | Agent (optional) | Provider credential for online Gemini calls. Leave empty for local/offline simulation. |
| `SWING_HTTPS_PORT` | Proxy | Optional loopback host port; default `8443`. Put a separate public TLS proxy/load balancer in front if external ingress is required. |

Generate three independent values with a cryptographically secure generator, for example `openssl rand -hex 32`. Never reuse one token across roles. Do not put secrets in `SWING_PUBLIC_*`, HTML, JavaScript, Docker build arguments, image labels, or command-line arguments.

The proxy forwards a caller's `Authorization` header unchanged. It does not authenticate users or mint bearer tokens. `SWING_AUTH_MODE=reverse_proxy` currently means the APIs enforce configured static bearer tokens; it is not OIDC. The `SWING_AUTH_ISSUER_URL`, audience, client, and session variables in `.env.example` are reserved and do not activate an identity provider. For an internet-facing, write-enabled deployment, integrate and verify an identity-aware gateway and browser login before enabling user access.

## TLS files and host setup

Provide `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem` through a protected deployment mechanism. The directory is ignored by Git and mounted read-only into Nginx. Ensure the certificate covers the hostname in `deploy/nginx/production.conf`, the DNS points to the host, and the host firewall only exposes the chosen TLS ingress. The bundled Compose proxy binds to loopback and does not expose port 80; its HTTP redirect block is for an outer proxy that forwards HTTP to it, otherwise remove/disable that block in the outer proxy configuration.

Set `SWING_ALLOWED_ORIGINS` to the browser's HTTPS origin exactly. Generate a fresh `.env` on the host from the secret manager; do not commit a populated copy. Verify with `docker compose config` using protected environment values and avoid publishing its output because Compose renders secrets in clear text.

## Rotation

To rotate, stop the stack, update the secret manager and host `.env`, then recreate both APIs in one maintenance window because the Agent and Twin must share the same internal token. Keep the old token revoked after the new deployment passes authenticated read and mutation checks. If a token may have leaked, revoke it immediately and inspect deployment access logs.
