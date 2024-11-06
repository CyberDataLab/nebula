import datetime
import ipaddress
import os

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_pem_private_key
from cryptography.x509.oid import NameOID


def generate_ca_certificate(dir_path):
    keyfile_path = os.path.join(dir_path, "ca_key.pem")
    certfile_path = os.path.join(dir_path, "ca_cert.pem")

    if os.path.exists(keyfile_path) and os.path.exists(certfile_path):
        print("CA Certificate and key already exist")
        return keyfile_path, certfile_path

    # Generate certfile and keyfile for the CA (pem format)
    ca_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    ca_issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "ES"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Spain"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Murcia"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nebula"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ca.nebula"),
    ])

    valid_from = datetime.datetime.utcnow()
    valid_to = valid_from + datetime.timedelta(days=365)

    cert = (
        x509.CertificateBuilder()
        .subject_name(ca_issuer)
        .issuer_name(ca_issuer)
        .public_key(ca_private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_private_key, hashes.SHA256(), default_backend())
    )

    with open(keyfile_path, "wb") as f:
        f.write(
            ca_private_key.private_bytes(
                encoding=Encoding.PEM,
                format=PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=NoEncryption(),
            )
        )

    with open(certfile_path, "wb") as f:
        f.write(cert.public_bytes(Encoding.PEM))

    return keyfile_path, certfile_path


def generate_certificate(dir_path, node_id, ip):
    keyfile_path = os.path.join(dir_path, f"{node_id}_key.pem")
    certfile_path = os.path.join(dir_path, f"{node_id}_cert.pem")
    ip_obj = ipaddress.ip_address(ip)

    if os.path.exists(keyfile_path) and os.path.exists(certfile_path):
        print("Certificate and key already exist")
        return keyfile_path, certfile_path

    with open(os.path.join(dir_path, "ca_key.pem"), "rb") as f:
        ca_private_key = load_pem_private_key(f.read(), password=None)

    with open(os.path.join(dir_path, "ca_cert.pem"), "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())

    # Generate certfile and keyfile for the participant to use in the federation (pem format)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nebula"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{node_id}.nebula"),
    ])

    valid_from = datetime.datetime.utcnow()
    valid_to = valid_from + datetime.timedelta(days=365)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ip_obj)]),
            critical=False,
        )
        .sign(ca_private_key, hashes.SHA256(), default_backend())
    )

    with open(keyfile_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=Encoding.PEM,
                format=PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=NoEncryption(),
            )
        )

    with open(certfile_path, "wb") as f:
        f.write(cert.public_bytes(Encoding.PEM))

    return keyfile_path, certfile_path


if __name__ == "__main__":
    current_dir = os.getcwd()
    generate_certificate(os.path.join(current_dir, "certs"))
