"""Exercise certificate verification with real TLS handshakes and no network sockets."""

import ssl
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from app.services import recruitment_tls


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    directory = tmp_path_factory.mktemp("source-tls")

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True)

    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "root.key",
            "-out", "root.pem", "-subj", "/CN=Isolated test root", "-days", "2",
            "-addext", "basicConstraints=critical,CA:true",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    for name, subject in (("intermediate", "Isolated test intermediate"), ("leaf", "lshsc.ng")):
        openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", name + ".key",
                "-out", name + ".csr", "-subj", "/CN=" + subject)
    (directory / "intermediate.ext").write_text(
        "basicConstraints=critical,CA:true,pathlen:0\n"
        "keyUsage=critical,keyCertSign,cRLSign\n"
        "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
    )
    (directory / "leaf.ext").write_text(
        "basicConstraints=critical,CA:false\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:lshsc.ng,DNS:www.lshsc.ng\n"
        "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
    )
    openssl("x509", "-req", "-in", "intermediate.csr", "-CA", "root.pem", "-CAkey", "root.key",
            "-set_serial", "2", "-days", "2", "-extfile", "intermediate.ext",
            "-out", "intermediate.pem")
    openssl("x509", "-req", "-in", "leaf.csr", "-CA", "intermediate.pem", "-CAkey",
            "intermediate.key", "-set_serial", "3", "-days", "2", "-extfile", "leaf.ext",
            "-out", "leaf.pem")
    # Newer OpenSSL releases reject negative -days. Give the expired certificate
    # a valid interval entirely in the past, with the same issuer and extensions.
    leaf = x509.load_pem_x509_certificate((directory / "leaf.pem").read_bytes())
    issuer_key = serialization.load_pem_private_key(
        (directory / "intermediate.key").read_bytes(), password=None
    )
    now = datetime.now(UTC)
    expired = (
        x509.CertificateBuilder()
        .subject_name(leaf.subject)
        .issuer_name(leaf.issuer)
        .public_key(leaf.public_key())
        .serial_number(4)
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now - timedelta(days=1))
    )
    for extension in leaf.extensions:
        expired = expired.add_extension(extension.value, critical=extension.critical)
    (directory / "expired.pem").write_bytes(
        expired.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    )
    (directory / "full.pem").write_text(
        (directory / "leaf.pem").read_text() + (directory / "intermediate.pem").read_text()
    )
    (directory / "empty-ca-dir").mkdir()
    return directory


@pytest.fixture
def trust(chain, monkeypatch):
    # Isolate system trust to a disposable test root. The bundled intermediate alone
    # must not authorize any server; that is tested below with the root removed.
    monkeypatch.setenv("SSL_CERT_FILE", str(chain / "root.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(chain / "empty-ca-dir"))
    monkeypatch.setattr(recruitment_tls, "INTERMEDIATE_BUNDLES", {
        "lshsc.ng": chain / "intermediate.pem", "www.lshsc.ng": chain / "intermediate.pem",
    })
    return chain


def handshake(context, chain, *, hostname="lshsc.ng", certificate="leaf.pem"):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(chain / certificate, chain / "leaf.key")
    client_in, client_out, server_in, server_out = [ssl.MemoryBIO() for _ in range(4)]
    client = context.wrap_bio(client_in, client_out, server_hostname=hostname)
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    complete = set()
    for _ in range(20):
        for peer, output, destination in (
            (client, client_out, server_in), (server, server_out, client_in),
        ):
            if peer not in complete:
                try:
                    peer.do_handshake()
                    complete.add(peer)
                except ssl.SSLWantReadError:
                    pass
            data = output.read()
            if data:
                destination.write(data)
        if len(complete) == 2:
            return client.getpeercert()
    raise AssertionError("TLS handshake did not complete")


@pytest.mark.parametrize("host", ["lshsc.ng", "www.lshsc.ng"])
def test_missing_intermediate_is_supplied_for_lshsc_only(trust, host):
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(ssl.create_default_context(), trust, hostname=host)
    context = recruitment_tls.source_ssl_context(host)
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert handshake(context, trust, hostname=host)["subjectAltName"]


@pytest.mark.parametrize("host", ["other.example.org", "lshsc.ng.other.example.org"])
def test_other_hosts_do_not_receive_the_compatibility_intermediate(trust, host):
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(recruitment_tls.source_ssl_context(host), trust)
    # Their normal valid full-chain connections are unaffected.
    assert handshake(recruitment_tls.source_ssl_context(host), trust, certificate="full.pem")


def test_missing_root_is_not_accepted_even_when_python_enables_partial_chains(trust, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(trust / "nonexistent-root.pem"))
    default_context = ssl.create_default_context

    def partial_chain_default():
        context = default_context()
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        return context

    monkeypatch.setattr(ssl, "create_default_context", partial_chain_default)
    context = recruitment_tls.source_ssl_context("lshsc.ng")
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(context, trust)


def test_hostname_mismatch_is_still_rejected(trust):
    with pytest.raises(ssl.SSLCertVerificationError) as error:
        handshake(recruitment_tls.source_ssl_context("lshsc.ng"), trust,
                  hostname="unrelated.example.org")
    assert error.value.verify_code == 62


def test_expired_certificate_is_still_rejected(trust):
    with pytest.raises(ssl.SSLCertVerificationError) as error:
        handshake(recruitment_tls.source_ssl_context("lshsc.ng"), trust, certificate="expired.pem")
    assert error.value.verify_code == 10
