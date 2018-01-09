# Microsoft Azure IoT Extension for Azure CLI 2.0

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)

This project provides new and exciting IoT commands and capabilities focused around IoT data-plane. Functionality is provided as an Azure CLI extension package for seamless integration.

## Features

The extension will augment vanilla Azure CLI IoT by adding to or modifying the existing command space. The following categories of capability are provided:

- IoT Hub
- IoT Edge
- IoT Device Provisioning Service _(coming soon)_

## Installation

The extension is designed to be plug and play with Azure CLI. **Even** if you have Azure CLI installed make sure it is up to date.

### Step 0: Install/Update Azure CLI

At a minimum your CLI core version must be `2.0.24` or above. Use `az --version` to validate. This version supports `az extension` commands and introduces the `knack` command framework.

Follow the installation instructions on [GitHub](https://github.com/Azure/azure-cli) or [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest) to setup Azure CLI in your environment.

### Step 1: Install the extension

Now that you have a compatible Azure CLI installed you can add the IoT extension.
When installing an extension any additional Python dependencies required will be downloaded and installed.

There are multiple options for installation. After following one, you can use `az extension list` to validate currently installed extensions or `az extension show --name azure-cli-iot-ext` to see details about this one.

In all cases, make sure the IoT extension is version **0.3.1** or greater.

#### Installation methods in prefered order

#### 1.a) Index method

Install the extension from the official Microsoft Azure CLI Extension Index

`az extension add --name azure-cli-iot-ext`

##### Index Tips

- You can use `az extension list-available` to see all available extensions on the index
- It is possible to update an extension in place using `az extension update --name <extension name>`

#### 1.b) URL or local package installation method

Go to this projects release tab in GitHub which contains past releases. Run the extension add command using the `--source` parameter.

The argument for the source parameter is either the URL download path (the extension package ends with '.whl') of your chosen release or the local path to the extension where you downloaded the release package.

`az extension add --source <local file path to release.whl OR  url for release.whl>`

For example to install version 0.3.1

`az extension add --source 'https://github.com/Azure/azure-iot-cli-extension/releases/download/v0.3.1/azure_cli_iot_ext-0.3.1-py2.py3-none-any.whl'`

#### 1.c) Package from source method

You can create a wheel package locally from source.

To build the wheel locally, ensure you have the `wheel` package installed i.e. `pip install wheel`. Then run `python setup.py bdist_wheel` where the current directory is the extension root.

Now follow the local package installation method.

### Step 2: Log In (if you haven't already)

Your subscription details are used to interact with target resources.

You can login interactively, pass in account credentials or use a service principal with password/certificate options.

[More details](https://docs.microsoft.com/en-us/cli/azure/authenticate-azure-cli?view=azure-cli-latest) about Azure CLI authentication.

### Step 3: Have Fun

If you have any suggestions or find bugs, please let us know.

To remove the extension at any time, you can use `az extension remove --name azure-cli-iot-ext`.

## Command Guide

Many commands require the default policy to exist on the target resource which is being manipulated. For example IoT Hub based commands commonly look for the 'iothubowner' policy. This behavior will change in a future update.

[Command Wiki](https://github.com/Azure/azure-iot-cli-extension/wiki/Commands)

## Developer setup

Extension development depends on a local Az CLI dev environment. First follow these [instructions](https://github.com/Azure/azure-cli/blob/master/doc/configuring_your_machine.md) for preparing your machine.

Next update your `AZURE_EXTENSION_DIR` environment variable to a target extension deployment directory. This overrides the standard extension directory.

Example `export AZURE_EXTENSION_DIR=~/.azure/devcliextensions/`

Run the following command to setup and install all dependencies in the extension deployment directory.

`pip install -U --target <extension deployment directory>/azure_cli_iot_ext <iot extension code root>`

Repeat the above command as needed.

At this point, assuming the setup is good the extension should be loaded and you should see the extension command space. Use `az --debug` and `az extension list` for debugging this step.

Helpful [Reference](https://github.com/Azure/azure-cli/tree/master/doc/extensions) docs for Az CLI Extension development

### Running Tests

Update the `PYTHONPATH` environment variable with both the extension dev deployment directory and root for the extension source code.

Example `export PYTHONPATH=~/.azure/devcliextensions/:~/source/azure_cli_iot_ext/`

Current testing patterns make heavy use of [pytest](https://docs.pytest.org/en/latest/) and [unittest](https://docs.python.org/3.6/library/unittest.html).

We also make use of the `pytest-mock` and `pytest-ordering` plugins for pytest.

After obtaining the above packages, ensure you have **activated** your Python virtual environment and your extension deployment directory is prepared.

**Unit tests:**

`pytest <extension root>/azext_iot/tests/test_iot_ext_unit.py`

**Integration tests:**

Currently integration tests leverage Azure CLI live scenario tests. Update the following environment variables prior to running integration tests.

`AZURE_TEST_RUN_LIVE` # Set to 'True' to hit live endpoints.

`azext_iot_testrg` # Target resource group for tests.

`azext_iot_testhub` # Target IoT Hub for respective category of tests.

Now you can run:

`pytest <extension root>/azext_iot/tests/test_iot_ext_int.py`

## Known Issues

- Device Export does not currently support IoT Edge device capability

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.