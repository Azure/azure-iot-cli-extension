#!/usr/bin/env bash
set -ex

# Install CLI & CLI testsdk
echo "Installing azure-cli-testsdk and azure-cli..."

# Update the git commit or branch when we need a new version of azure-cli-testsdk
pip install "git+https://github.com/Azure/azure-cli@master#egg=azure-cli-testsdk&subdirectory=src/azure-cli-testsdk" -q
echo "Installed."
az --version

EXT='azure-cli-iot-ext'

echo "Setting up extension directory..."
export AZURE_EXTENSION_DIR=$(mktemp -d)
pip install --upgrade --target $AZURE_EXTENSION_DIR/$EXT .
az --debug

export PYTHONPATH=$AZURE_EXTENSION_DIR/$EXT/:$(pwd)/

echo "Running tests..."
echo "Executing - IoT Hub unit tests"
pytest -v azext_iot/tests/test_iot_ext_unit.py

echo "Executing - DPS unit tests"
pytest -v azext_iot/tests/test_iot_dps_unit.py


echo "Tests completed."
