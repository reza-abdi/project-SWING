"""Static preflight for the single-host Compose deployment bundle."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate() -> list[str]:
    errors: list[str] = []
    compose_path = ROOT / "compose.yaml"
    compose = compose_path.read_text(encoding="utf-8")
    required = (
        "SWING_ALLOWED_ORIGINS", "SWING_OPERATOR_TOKEN", "SWING_ADMIN_TOKEN",
        "SWING_INTERNAL_TWIN_TOKEN",
    )
    for name in required:
        if not re.search(rf"\$\{{{name}:\?", compose):
            errors.append(f"compose.yaml must fail closed when {name} is missing")
    app_services = re.findall(r"(?ms)^  (?:twin|agent):\n(.*?)(?=^  [\w-]+:\n|\Z)", compose)
    if len(app_services) != 2 or any(re.search(r"(?m)^    ports:", service) for service in app_services):
        errors.append("Twin and Agent services must not publish host ports")
    for fragment in ("twin.conf", "agent.conf"):
        if not (ROOT / "deploy/nginx" / fragment).is_file():
            errors.append(f"missing nginx fragment: {fragment}")
    for dockerfile in ("Dockerfile.twin", "Dockerfile.agent"):
        path = ROOT / dockerfile
        if not path.is_file():
            errors.append(f"missing image definition: {dockerfile}")
        elif not re.search(r"(?m)^FROM\s+\S+@sha256:[0-9a-f]{64}", path.read_text(encoding="utf-8")):
            errors.append(f"{dockerfile} must pin its base image by digest")
    if not re.search(r"(?m)^    image: nginx:[^\s]+@sha256:[0-9a-f]{64}$", compose):
        errors.append("proxy image must pin the official Nginx image by digest")
    if 'entrypoint: ["nginx"]' not in compose or 'command: ["-g", "daemon off;"]' not in compose:
        errors.append("read-only Nginx config must bypass image entrypoint mutation scripts")
    if compose.count('security_opt: ["no-new-privileges:true"]') != 3 or compose.count("cap_drop: [ALL]") != 3:
        errors.append("all containers must disable privilege escalation and drop ambient capabilities")
    if "cap_add: [NET_BIND_SERVICE]" not in compose:
        errors.append("TLS proxy must retain only the capability needed to bind port 443")
    if "swing-state:/var/lib/swing" not in compose:
        errors.append("both services must mount persistent event storage")
    if "127.0.0.1:${SWING_HTTPS_PORT:-8443}:443" not in compose:
        errors.append("TLS ingress must remain bound to host loopback by default")
    if "ipv4_address: 172.29.245.10" not in compose or "172.29.245.0/24" not in compose:
        errors.append("proxy address and trusted-proxy subnet must match")
    for name in required:
        value = re.search(rf"(?m)^{name}=(.*)$", (ROOT / ".env.example").read_text(encoding="utf-8"))
        if value and value.group(1).strip():
            errors.append(f".env.example must not contain a value for {name}")
    if (ROOT / "deploy/certs/privkey.pem").exists():
        errors.append("private TLS key must not be present in the repository")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Deployment preflight passed (static contract only; Docker/Nginx runtime not checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
