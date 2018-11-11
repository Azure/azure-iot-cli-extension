# Microsoft Azure IoT Extension for Azure CLI

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)

The **Azure IoT Extension for Azure CLI** adds _IoT Hub_, _IoT Edge_, and _IoT Device Provisioning Service (DPS)_ specific commands to the official [Azure CLI](https://docs.microsoft.com/en-us/cli/azure).

## Commands
Please refer to the official "az iot" page on [Microosft Docs](https://docs.microsoft.com/en-us/cli/azure/ext/azure-cli-iot-ext) for a complete list of supported commands.  You can also find IoT CLI usage tips on the [wiki](https://github.com/Azure/azure-iot-cli-extension/wiki/Tips).

## Installation

1. Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
    - You must have at least `v2.0.24`, which you can verify with `az --version`
1. Add, Update or Remove the IoT Extension with the following commands:
    - Add: `az extension add --name azure-cli-iot-ext`
    - Update: `az extension update --name azure-cli-iot-ext`
    - Remove: `az extension remove --name azure-cli-iot-ext`

Please refer to the [Installation Troubleshooting Guide](docs/install-help.md) if you run into any issues or the [Alternative Installation Methods](docs/alt-install-methods.md) if you'd like to install from local source.

## Scenario Automation
Please refer to the [Example Automation Scripts](docs/scenario-automation.md) page for an example of how to use the IoT CLI to automate your scenarios.

## Contributing
Please refer to the [Contributing](contributing.md) page for developer setup instructions and contribution guidelines.


## Code of Conduct
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.
