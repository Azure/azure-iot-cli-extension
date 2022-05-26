import datetime
from os.path import exists, join
import base64
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def open_cert(cert_dir, key_dir, password=None):
    print(cert_dir)
    print()
    pem_cert_text = ""
    with open(cert_dir, "rb") as cert_file:
        pem_cert_text = cert_file.read()

    pem_key_text = ""
    with open(key_dir, "rb") as cert_file:
        pem_key_text = cert_file.read()

    root_cert = x509.load_pem_x509_certificate(pem_cert_text)
    root_key = load_pem_private_key(pem_key_text, password=password)
    import pdb; pdb.set_trace()
    print(root_cert)

if input("ubuntu? ").strip().lower() == "y":
    ubuntu = "../cert_stuff_from_ubuntu/"
    CERT_PAIRS = [
        ("certs/azure-iot-test-only.root.ca.cert.pem", "private/azure-iot-test-only.root.ca.key.pem"),
        # ("certs/azure-iot-test-only.intermediate.cert.pem", "private/azure-iot-test-only.intermediate.key.pem"),
        # ("certs/new-device-01-full-chain.cert.pem", "private/new-device.key.pem"),
        ("certs/new-device.cert.pem", "private/new-device.key.pem"),
    ]
    for cert, key in CERT_PAIRS:
        password = b'1234' if "root" in cert else None
        open_cert(f"{ubuntu}{cert}", f"{ubuntu}{key}", password)
else:
    pythonfold = "../cert_stuff_from_python/"
    CERT_PAIRS = [
        ("Banana_Tree_Root21-cert.pem", "Banana_Tree_Root21-key.pem"),
        ("BananaLeaf21_1-cert.pem", "BananaLeaf21_1-key.pem"),
        ("BananaLeaf21_1-fullchain-cert.pem", "BananaLeaf21_1-key.pem"),
    ]
    for cert, key in CERT_PAIRS:
        open_cert(f"{pythonfold}{cert}", f"{pythonfold}{key}")
