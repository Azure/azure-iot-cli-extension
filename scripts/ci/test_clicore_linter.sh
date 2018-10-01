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

echo "Generating wheel..."
python setup.py bdist_wheel
target_wheel=`ls dist | head -n 1`

echo "Installing IoT extension via source method..."
az extension add --source ./dist/$target_wheel --yes

echo "Executing linter..."
azdev cli-lint --ci --extensions azure-cli-iot-ext

echo "Removing extension..."
az extension remove --name azure-cli-iot-ext
