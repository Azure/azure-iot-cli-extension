#!/bin/sh

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

echo "Setting up CLI dev environment"

# Install virtualenv
python -m venv env
source env/bin/activate

# Install azdev
echo "Install AZDEV"
pip install azdev

# Install CLI core (EDGE) and configure extension repo
echo "azdev setup"
azdev setup -c EDGE

# install dev requirements (overrides setuptools)
echo "Installing extension and dev requirements..."
pip install -r dev_requirements
pip install -U --target ~/.azure/cliextensions/azure-iot .

# setup tox environment dependencies in parallel, but don't run tests
echo "Creating local tox environments..."
python -m pip install tox
tox -np
