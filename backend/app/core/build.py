"""Build-stamped vendor constants — the root of trust for licensing.

Both values here decide whether the licensing gate can be bypassed, so neither is
an environment variable and neither is read from a file: the client controls the
environment and the filesystem of their own server, we control the image.

``VENDOR_PUBLIC_KEY_PEM`` is the Ed25519 public key every license is verified
against. Embedding it here (rather than reading ``deploy/license_pubkey.pem``)
stops a client from dropping in a keypair of their own and self-signing a
perpetual license. ``python -m app.tools.license keygen`` stamps it — vendor-side,
run once, and back up the private key it writes because it cannot be recovered.

``PRODUCTION_BUILD`` turns license enforcement on. The repo ships ``False`` so
dev, tests and self-hosting run unlicensed; ``backend/Dockerfile`` rewrites it to
``True`` when building a release image (``--build-arg PRODUCTION_BUILD=true``,
which is the default). There is deliberately no env override — ``ENFORCE_LICENSE``
used to exist and was a one-line bypass for anyone with access to ``.env``.

Neither constant is a secret: the public key is public by definition and the flag
is a boolean. They are here to remove the *easy* bypass. Making them genuinely
hard to patch out needs the compiled-build work (Layer 3), not more Python.
"""
from __future__ import annotations

# Stamped by `python -m app.tools.license keygen`. Empty means unconfigured:
# harmless in a dev build, a fatal misbuild in a release image.
VENDOR_PUBLIC_KEY_PEM = ""

# Rewritten to True by backend/Dockerfile at image build time.
PRODUCTION_BUILD = False
