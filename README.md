# Microsoft Azure IoT Extension for Azure CLI

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)

This project provides new and exciting IoT commands and capabilities focused around the IoT Hub and IoT Device Provisioning services. Functionality is provided as an Azure CLI extension package for seamless integration with existing command-line functionality.

## Features

The extension augments the vanilla Azure CLI IoT by adding to or modifying the existing command space. The extension includes capabilities in the following categories:

- IoT Hub
- IoT Edge
- IoT Device Provisioning Service (DPS)

## Installation

The extension is designed to be plug-and-play with Azure CLI. **Even** if you have Azure CLI installed make sure it is up to date.

:exclamation: For **installation troubleshooting** please go to the [respective docs section](docs/install-help.md) for help.

### Compatibility
Before installation ensure that your Azure CLI version meets the following criteria. The criteria differs based on OS and method of installation. Use `az --version` to determine the CLI version.

In all cases your CLI needs to be at least `v2.0.24`.

| CLI Install Method  | NOT compatible with |
| ------------- | ------------- |
| Windows via MSI  | v2.0.34 to v2.0.38  |
| Windows via PIP, Linux or macOS  | v2.0.34 to v2.0.36  |


### Quick Guide

Validate that your Azure CLI version is [compatible](#compatibility).

**Common Az CLI extension operations**

Add: `az extension add --name azure-cli-iot-ext`

List: `az extension list`

Update: `az extension update --name azure-cli-iot-ext`

Remove: `az extension remove --name azure-cli-iot-ext`


### Full Guide

#### Step 0: Install/Update Azure CLI

At a minimum your CLI core version must be within the [compatibility](#compatibility) criteria defined above.

Follow the installation instructions on [GitHub](https://github.com/Azure/azure-cli) or [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest) to setup Azure CLI in your environment.

#### Step 1: Install the extension

Now that you have a compatible Azure CLI installed you can add the IoT extension.
When you install an extension, any additional Python dependencies required are automatically downloaded and installed.

There are multiple options for installation. After installing the extension, you can use `az extension list` to validate the currently installed extensions or `az extension show --name azure-cli-iot-ext` to see details about the IoT extension.

In all cases, make sure the IoT extension is version **0.3.2** or greater.

#### Installation methods in preferred order

#### 1.a) Index method

Install the extension from the official Microsoft Azure CLI Extension Index

`az extension add --name azure-cli-iot-ext`

##### Index Tips

- You can use `az extension list-available` to see all available extensions on the index
- It is possible to update an extension in place using `az extension update --name <extension name>`

#### 1.b) URL or local package installation method

Navigate to this project's release tab in GitHub to see the list of releases. Run the extension add command using the `--source` parameter.

The argument for the source parameter is either the URL download path (the extension package ends with '.whl') of your chosen release, or the local path to the extension where you downloaded the release package.

`az extension add --source <local file path to release.whl OR  url for release.whl>`

For example, to install version 0.3.2

`az extension add --source 'https://github.com/Azure/azure-iot-cli-extension/releases/download/v0.3.2/azure_cli_iot_ext-0.3.2-py2.py3-none-any.whl'`

#### 1.c) Package from source method

You can create a wheel package locally from source to be used in Azure CLI.

To build the wheel locally, ensure you have the Python `wheel` package installed i.e. `pip install wheel`. Then run `python setup.py bdist_wheel` where the current directory is the extension root. The wheel (with .whl suffix) will be generated and available in the new `dist` folder.

Now follow the local package installation method.

#### Step 2: Log In (if you haven't already)

Your subscription details are used to interact with target resources.

You can login interactively, pass in account credentials, or use a service principal with password/certificate options.

[More details](https://docs.microsoft.com/en-us/cli/azure/authenticate-azure-cli?view=azure-cli-latest) about Azure CLI authentication.

#### Step 3: Have Fun

If you have any suggestions or find bugs, please let us know.

To remove the extension at any time, you can use `az extension remove --name azure-cli-iot-ext`.

:exclamation: For **installation troubleshooting** please go to the [respective docs section](docs/install-help.md) for help.

## Command Guide

The [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/ext/azure-cli-iot-ext/iot?view=azure-cli-latest) extensions reference are updated per release.

#### Tips for success

* Many commands require the default policy to exist on the target resource which is being manipulated. For example IoT Hub based commands commonly look for the **iothubowner** policy. _This behavior will change in a future update_.

* For command parameters that take JSON, for example the `az iot hub device-twin update` command's `--set` parameter, the JSON input format is different between CMD/PowerShell and Bash-like shells.

Please read the [Tips Wiki page](https://github.com/Azure/azure-iot-cli-extension/wiki/Tips) for more detail and to maximize the functionality and enjoyment out of the IoT extension.

## Scenario Automation

Jump start your Azure IoT automation experience by checking out [example automation scripts](docs/scenario-automation.md) using the IoT extension!

## Developer setup

Extension development depends on a local Azure CLI dev environment. First, follow these [instructions](https://github.com/Azure/azure-cli/blob/master/doc/configuring_your_machine.md) to prepare your machine.

Next, update your `AZURE_EXTENSION_DIR` environment variable to a target extension deployment directory. This overrides the standard extension directory.

Example `export AZURE_EXTENSION_DIR=~/.azure/devcliextensions/`

Run the following command to setup and install all dependencies in the extension deployment directory.

`pip install -U --target <extension deployment directory>/azure-cli-iot-ext <iot extension code root>`

Repeat the above command as needed.

At this point, assuming the setup is good the extension should be loaded and you should see the extension command space. Use `az --debug` and `az extension list` for debugging this step.

Helpful [Reference](https://github.com/Azure/azure-cli/tree/master/doc/extensions) docs for Az CLI Extension development

### Running Tests

Update the `PYTHONPATH` environment variable with both the extension dev deployment directory and root for the extension source code.

Example `export PYTHONPATH=~/.azure/devcliextensions/azure-cli-iot-ext/:~/source/azure-cli-iot-ext/`

Current testing patterns make use of [pytest](https://docs.pytest.org/en/latest/) and [unittest](https://docs.python.org/3.6/library/unittest.html). We also use `pytest-mock` and `pytest-cov` plugins for pytest so make sure you `pip install` these dependencies beforehand. You can leverage our `requirements` file at the root of this project to install from.

After obtaining the above, ensure you have **activated** your Python virtual environment and your extension deployment directory is prepared.

#### Unit tests

_Hub:_  
`pytest <extension root>/azext_iot/tests/test_iot_ext_unit.py`

_DPS:_  
`pytest <extension root>/azext_iot/tests/test_iot_dps_unit.py`

#### Integration tests

Currently integration tests leverage Azure CLI live scenario tests. Update the following environment variables OR use an updated pytest.ini (copying and renaming pytest.ini.example) in the extension root directory prior to running integration tests.

These variables are **shared** between Hub and DPS integration tests:

`AZURE_TEST_RUN_LIVE` # Set to 'True' to hit live endpoints.

`azext_iot_testrg` # Target resource group for tests.

`azext_iot_testhub` # Target IoT Hub for respective category of tests.

Now you can run **Hub** integration tests:

`pytest <extension root>/azext_iot/tests/test_iot_ext_int.py`

_Optionally_ set `azext_iot_teststorageuri` to your empty blob container sas uri to test device export and enable file upload test. For file upload, you will need to have configured your IoT Hub before running.

For **DPS** update the following environment variable prior to running.

`azext_iot_testdps` # Target IoT Hub DPS for respective category of tests.

Now you can run **DPS** integration tests:

`pytest <extension root>/azext_iot/tests/test_iot_dps_int.py`

#### All tests and coverage in one command

At this point if your environment has been setup to execute all tests, you can leverage pytest discovery to run all tests and provide a coverage report.

`pytest -v <extension root> --cov=azext_iot --cov-config <extension root>/.coveragerc`


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
