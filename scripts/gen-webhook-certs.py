#!/usr/bin/env python3
"""Generate a self-signed CA + serving cert for the admission webhook.

The webhook must serve HTTPS and kube-apiserver must trust the cert. For
the demo we generate everything fresh on each deploy:
  - A CA key + self-signed CA cert
  - A leaf serving cert signed by that CA, with SANs for the in-cluster DNS name
  - A Kubernetes TLS Secret containing the leaf cert + key
  - The CA bundle written to stdout (base64) for piping into ValidatingWebhookConfiguration

Usage:
  scripts/gen-webhook-certs.py --service admission-webhook --namespace agent-warden-system

This script depends only on Python stdlib + the `cryptography` package,
which is already in our operator requirements. No openssl CLI needed.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print(
        "error: cryptography package not installed. Run: pip install cryptography",
        file=sys.stderr,
    )
    sys.exit(2)


def _make_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_ca(key: rsa.RSAPrivateKey) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-warden-ca")])
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )


def _make_leaf(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    service: str,
    namespace: str,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    leaf_key = _make_key()
    common_name = f"{service}.{namespace}.svc"
    sans = [
        x509.DNSName(service),
        x509.DNSName(f"{service}.{namespace}"),
        x509.DNSName(f"{service}.{namespace}.svc"),
        x509.DNSName(f"{service}.{namespace}.svc.cluster.local"),
    ]
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return leaf_key, cert


def _pem_cert(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _pem_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--service", required=True)
    p.add_argument("--namespace", required=True)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tls"),
        help="Where to write tls.crt, tls.key, and ca.crt",
    )
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    ca_key = _make_key()
    ca_cert = _make_ca(ca_key)
    leaf_key, leaf_cert = _make_leaf(ca_key, ca_cert, args.service, args.namespace)

    ca_pem = _pem_cert(ca_cert)
    leaf_pem = _pem_cert(leaf_cert)
    key_pem = _pem_key(leaf_key)

    (args.out_dir / "ca.crt").write_bytes(ca_pem)
    (args.out_dir / "tls.crt").write_bytes(leaf_pem)
    (args.out_dir / "tls.key").write_bytes(key_pem)

    # Emit the base64 CA bundle on stdout - useful for kubectl patch
    print(base64.b64encode(ca_pem).decode())
    print(
        f"wrote ca.crt, tls.crt, tls.key to {args.out_dir}/",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
