#!/usr/bin/env bash
set -ex

# Install CLI & CLI testsdk
echo "Installing azure-cli-testsdk and azure-cli..."

# Update the git commit or branch when we need a new version of azure-cli-testsdk
pip install --pre azure-cli --extra-index-url https://azurecliprod.blob.core.windows.net/edge
pip install -e "git+https://github.com/Azure/azure-cli@dev#egg=azure-cli-dev-tools&subdirectory=tools" -q

echo "Installed."
az --version
set +x

EXT='azure-cli-iot-ext'

echo "Setting up extension directory..."
export AZURE_EXTENSION_DIR=$(mktemp -d)
pip install --upgrade --target $AZURE_EXTENSION_DIR/$EXT .
az --debug

export PYTHONPATH=$AZURE_EXTENSION_DIR/$EXT/:$(pwd)/

echo "Running IoT extension unit tests..."
echo "Executing - IoT Hub unit tests"
pytest -v azext_iot/tests/test_iot_ext_unit.py

echo "Executing - DPS unit tests"
pytest -v azext_iot/tests/test_iot_dps_unit.py

echo "Executing - Utility unit tests"
pytest -v azext_iot/tests/test_iot_utility_unit.py

echo "Executing - Pnp unit tests"
pytest -v azext_iot/tests/test_iot_pnp_unit.py

echo "Executing - Digitaltwin unit tests"
pytest -v azext_iot/tests/test_iot_digitaltwin_unit.py

echo "Tests completed."
