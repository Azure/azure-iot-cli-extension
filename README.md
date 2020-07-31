# Microsoft Azure IoT extension for Azure CLI

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)
![Build Status](https://dev.azure.com/azureiotdevxp/aziotcli/_apis/build/status/Merge%20-%20Azure.azure-iot-cli-extension?branchName=dev)


The **Azure IoT extension for Azure CLI** aims to accelerate the development, management and automation of Azure IoT solutions. It does this via addition of rich features and functionality to the official [Azure CLI](https://docs.microsoft.com/en-us/cli/azure).

## News

The legacy IoT extension Id `azure-cli-iot-ext` is deprecated in favor of the new modern Id `azure-iot`. `azure-iot` is a superset of `azure-cli-iot-ext` and any new features or fixes will apply to `azure-iot` only. Also the legacy and modern IoT extension should **never** co-exist in the same CLI environment.

Related - if you see an error with a stacktrace similar to:
```
...
azure-cli-iot-ext/azext_iot/common/_azure.py, ln 90, in get_iot_hub_connection_string
    client = iot_hub_service_factory(cmd.cli_ctx)
cliextensions/azure-cli-iot-ext/azext_iot/_factory.py, ln 29, in iot_hub_service_factory
    from azure.mgmt.iothub.iot_hub_client import IotHubClient
ModuleNotFoundError: No module named 'azure.mgmt.iothub.iot_hub_client'
```

The resolution is to remove the deprecated `azure-cli-iot-ext` and install any version of the `azure-iot` extension. 


## Commands

Please refer to the official `az iot` reference on [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/ext/azure-iot/iot?view=azure-cli-latest) for a complete list of supported commands.  You can also find IoT CLI usage tips on the [wiki](https://github.com/Azure/azure-iot-cli-extension/wiki/Tips).

## Installation

1. Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
    - You must have at least `v2.0.70`, which you can verify with `az --version`
1. Add, Update or Remove the IoT extension with the following commands:
    - Add: `az extension add --name azure-iot`
    - Update: `az extension update --name azure-iot`
    - Remove: `az extension remove --name azure-iot`

Please refer to the [Installation Troubleshooting Guide](docs/install-help.md) if you run into any issues or the [Alternative Installation Methods](docs/alt-install-methods.md) if you'd like to install from a GitHub release or local source.

## Usage

After installing the Azure IoT extension your CLI environment is augmented with the addition of `central`, `device`, `dps`, `dt`, `edge`, `hub` and `pnp` commands.

For usage and help content for any command or command group, pass in the `-h` parameter, for example:

```
$ az iot hub -h
Group
    az iot hub : Manage entities in an Azure IoT Hub.

Subgroups:
    certificate                   : Manage IoT Hub certificates.
    configuration                 : Manage IoT device configurations at scale.
    consumer-group                : Manage the event hub consumer groups of an IoT hub.
    device-identity               : Manage IoT devices.
    device-twin                   : Manage IoT device twin configuration.
    devicestream                  : Manage device streams of an IoT hub.
    distributed-tracing [Preview] : Manage distributed settings per-device.
    job                           : Manage jobs in an IoT hub.
    message-enrichment            : Manage message enrichments for endpoints of an IoT Hub.
    module-identity               : Manage IoT device modules.
    module-twin                   : Manage IoT device module twin configuration.
    policy                        : Manage shared access policies of an IoT hub.
    route                         : Manage routes of an IoT hub.
    routing-endpoint              : Manage custom endpoints of an IoT hub.

Commands:
    create                        : Create an Azure IoT hub.
    delete                        : Delete an IoT hub.
    generate-sas-token            : Generate a SAS token for a target IoT Hub, device or module.
    invoke-device-method          : Invoke a device method.
    invoke-module-method          : Invoke an Edge module method.
    list                          : List IoT hubs.
    list-skus                     : List available pricing tiers.
    manual-failover               : Initiate a manual failover for the IoT Hub to the geo-paired
                                    disaster recovery region.
    monitor-events                : Monitor device telemetry & messages sent to an IoT Hub.
    monitor-feedback              : Monitor feedback sent by devices to acknowledge cloud-to-device
                                    (C2D) messages.
    query                         : Query an IoT Hub using a powerful SQL-like language.
    show                          : Get the details of an IoT hub.
    show-connection-string        : Show the connection strings for an IoT hub.
    show-quota-metrics            : Get the quota metrics for an IoT hub.
    show-stats                    : Get the statistics for an IoT hub.
    update                        : Update metadata for an IoT hub.
```

## Scenario Automation

Please refer to the [Scenario Automation](docs/scenario-automation.md) page for examples of how to use the IoT extension in scripts.

## Contributing

Please refer to the [Contributing](CONTRIBUTING.md) page for developer setup instructions and contribution guidelines.

## Feedback

We are constantly improving and are always open to new functionality or enhancement ideas. Submit your feedback in the project [issues](https://github.com/Azure/azure-iot-cli-extension/issues).

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.
