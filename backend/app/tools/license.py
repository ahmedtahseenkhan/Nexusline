"""Vendor CLI for offline licensing.

  python -m app.tools.license keygen  --out deploy
  python -m app.tools.license sign    --key deploy/license_signing_key.pem \
        --to "Habib Bank Ltd" --plan enterprise --seats 250 --days 365 \
        --features internal_audit,ldap,mfa,operational_risk --out deploy/license.key
  python -m app.tools.license verify  deploy/license.key

`keygen` produces the vendor private key (KEEP SECRET) and the public key that ships
with the deployment. `sign` mints a signed license token. `verify` checks one locally.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from app.services import license as lic


def _keygen(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    private_pem, public_pem = lic.generate_keypair()
    priv_path = out / "license_signing_key.pem"
    pub_path = out / "license_pubkey.pem"
    priv_path.write_bytes(private_pem)
    pub_path.write_bytes(public_pem)
    priv_path.chmod(0o600)
    print(f"Wrote private signing key -> {priv_path}  (KEEP SECRET; do not ship)")
    print(f"Wrote public key         -> {pub_path}   (ship with the deployment)")
    return 0


def _sign(args: argparse.Namespace) -> int:
    payload = {
        "licensed_to": args.to,
        "plan": args.plan,
        "seats": args.seats,
        "features": [f.strip() for f in args.features.split(",") if f.strip()],
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=args.days)).isoformat(),
        "deployment": args.deployment,
    }
    token = lic.sign_payload(payload, Path(args.key).read_bytes())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(token)
    print(f"Signed license for '{args.to}' ({args.plan}, {args.seats} seats), "
          f"expires {payload['expires']}")
    print(f"Wrote -> {args.out}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    token = Path(args.file).read_text()
    info = lic.verify_token(token)
    for k, v in info.to_public().items():
        print(f"  {k:12} {v}")
    return 0 if info.valid else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.tools.license", description="Offline license CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="Generate a vendor Ed25519 keypair")
    kg.add_argument("--out", default="deploy")
    kg.set_defaults(fn=_keygen)

    sg = sub.add_parser("sign", help="Sign a license token")
    sg.add_argument("--key", required=True, help="Path to the private signing key PEM")
    sg.add_argument("--to", required=True, help="Licensed organization name")
    sg.add_argument("--plan", default="enterprise")
    sg.add_argument("--seats", type=int, default=100)
    sg.add_argument("--days", type=int, default=365)
    sg.add_argument("--features", default="", help="Comma-separated feature flags")
    sg.add_argument("--deployment", default="on-prem")
    sg.add_argument("--out", default="deploy/license.key")
    sg.set_defaults(fn=_sign)

    vf = sub.add_parser("verify", help="Verify a license token file")
    vf.add_argument("file")
    vf.set_defaults(fn=_verify)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
