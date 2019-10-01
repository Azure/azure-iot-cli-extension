#!/usr/bin/env bash
set -ex

# Install CLI & CLI testsdk
echo "Installing azure-cli-testsdk and azure-cli..."

# Update the git commit or branch when we need a new version of azure-cli-testsdk
pip install --pre azure-cli --extra-index-url https://azurecliprod.blob.core.windows.net/edge
pip install -e "git+https://github.com/Azure/azure-cli@dev#egg=azure-cli-testsdk&subdirectory=src/azure-cli-testsdk"

echo "Installed."
az --version
set +x

EXT='azure-cli-iot-ext'

echo "Setting up extension directory..."
export AZURE_EXTENSION_DIR=$(mktemp -d)
pip install --upgrade --target $AZURE_EXTENSION_DIR/$EXT .
pip install -r dev_requirements

az --debug

echo "Running IoT extension unit tests..."
echo "Executing - IoT Hub unit tests"
pytest -v azext_iot/tests/test_iot_ext_unit.py

echo "Executing - DPS unit tests"
pytest -v azext_iot/tests/test_iot_dps_unit.py

echo "Executing - Utility unit tests"
pytest -v azext_iot/tests/test_iot_utility_unit.py

echo "Executing - IoT Central unit tests"
pytest -v azext_iot/tests/test_iot_central_unit.py

echo "Executing - Pnp unit tests"
pytest -v azext_iot/tests/test_iot_pnp_unit.py

echo "Executing - Digitaltwin unit tests"
pytest -v azext_iot/tests/test_iot_digitaltwin_unit.py

echo "Tests completed."

proc_number=`python -c 'import multiprocessing; print(multiprocessing.cpu_count())'`

echo "Running IoT extension linters..."

# Run pylint/flake8 on IoT extension
pylint azext_iot/ --rcfile=.pylintrc -j $proc_number
flake8 azext_iot/ --statistics --config=setup.cfg
