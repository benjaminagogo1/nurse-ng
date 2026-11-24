"""Host-scoped missing intermediates; system roots remain the trust anchors.

Only the documented LSHSC hostnames receive the bundled intermediate. System
roots and hostname checks remain active; this is not a global TLS-verification
bypass. See app/certificates/README.md.
"""

import ssl
from pathlib import Path

_SECTIGO_DV_R36 = (
    Path(__file__).resolve().parents[1]
    / "certificates"
    / "sectigo-public-server-authentication-ca-dv-r36.pem"
)
INTERMEDIATE_BUNDLES = {"lshsc.ng": _SECTIGO_DV_R36, "www.lshsc.ng": _SECTIGO_DV_R36}


def source_ssl_context(host: str) -> ssl.SSLContext:
    context = ssl.create_default_context()
    bundle = INTERMEDIATE_BUNDLES.get(host.lower())
    if bundle is not None:
        # Python 3.13+ enables partial-chain trust by default. An intermediate must
        # never become our trust anchor: still require a root in the system store.
        context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
        context.load_verify_locations(cafile=str(bundle))
    return context
