#small test script
import random
import subprocess
import json
from azext_iot.common.certops import create_key_signed_certificate, create_self_signed_certificate


number_picked = random.randint(0, 100)
print(f"Number for the run {number_picked}")
RG = "vilit"
HUB_NAME = "vilit-hub-test"
DPS_NAME = f"vilit-dps-gen-{number_picked}"

CERT_DIR = "../cert_stuff_from_python/"

ROOT_CERT = f"Banana_Tree_Root{number_picked}"
LEAF_CERTS = [
    f"BananaLeaf{number_picked}_1",
    f"BananaLeaf{number_picked}_2"
]

root_cert = create_self_signed_certificate(ROOT_CERT, 30, CERT_DIR, allowed_signing=None)
leaf_cert_objects = []
device_chain_certs = []
for leaf_cert in LEAF_CERTS:
    leaf_cert_objects.append(
        create_key_signed_certificate(leaf_cert, 30, CERT_DIR, cert_object=root_cert)
    )
    with open(f"{CERT_DIR}{leaf_cert}-cert.pem") as device, open(f"{CERT_DIR}{ROOT_CERT}-cert.pem") as root, open(f"{CERT_DIR}{leaf_cert}-fullchain-cert.pem", "wt") as chain:
        chain.write(device.read())
        chain.write(root.read())


def dps_setup():
    # dps setup
    dps_result = subprocess.run(
        f"az iot dps create -n {DPS_NAME} -g {RG} ",
        shell=True,
        capture_output=True,
        text=True
    ).stdout
    id_scope = json.loads(dps_result)["properties"]["idScope"]
    print(f"created the dps {DPS_NAME}")

    subprocess.run(
        f"az iot dps linked-hub create --dps-name {DPS_NAME} -g {RG} --hub-name {HUB_NAME}",
        shell=True,
        capture_output=True,
        text=True
    )
    print("added the linked hub")

    subprocess.run(
        f"az iot dps certificate create --dps-name {DPS_NAME} -g {RG} -n {HUB_NAME} -v -p {CERT_DIR}{ROOT_CERT}-cert.pem",
        shell=True,
        text=True,
        stdout=subprocess.PIPE
    )
    print("added the certificate to the dps")
    return id_scope

def dps_enrollment_group_setup(enroll_cert):
    print(f"using {enroll_cert} for enrollment group\n")
    print(f"az iot dps enrollment-group create -n {DPS_NAME} -g {RG} --gid enrollment --cp {CERT_DIR}{enroll_cert}-cert.pem")
    subprocess.run(
        f"az iot dps enrollment-group create -n {DPS_NAME} -g {RG} --gid enrollment --cp {CERT_DIR}{enroll_cert}-cert.pem",
        shell=True,
        text=True,
        stdout=subprocess.PIPE
    )

def dps_device_register(id_scope, device_name):
    print(f"using {device_name}\n")
    print("cmd")
    print(f"az iot device registration create --id-scope {id_scope} --rid {device_name} --cp {CERT_DIR}{device_name}-fullchain-cert.pem --kp {CERT_DIR}{device_name}-key.pem")
    print()
    subprocess.run(
        f"az iot device registration create --id-scope {id_scope} --rid {device_name} --cp {CERT_DIR}{device_name}-fullchain-cert.pem --kp {CERT_DIR}{device_name}-key.pem",
        shell=True,
        text=True,
        stdout=subprocess.PIPE
    )

def dps_teardown():
    subprocess.run(
        f"az iot dps delete -n {DPS_NAME} -g {RG} ",
        shell=True,
        capture_output=True,
        text=True
    )

if __name__ == "__main__":
    print("--------------------------------created the cert stuffs--------------------------------")
    if input("continue with creating dps? ").strip().lower() == "y":
        try:
            id_scope = dps_setup()
            print(f"\n--------------------------------created dps - {DPS_NAME}--------------------------------\n")
            dps_enrollment_group_setup(ROOT_CERT)
            print("--------------------------------created the enrollment group--------------------------------")

            for device in LEAF_CERTS:
                print(f"\n-----Trying {device}")
                dps_device_register(id_scope, device)
            print("\ndone")
            if input("delete dps? ").strip().lower() == "y":
                dps_teardown()

        except Exception as e:
            dps_teardown()
            raise e