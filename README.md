# Microsoft Azure IoT extension for Azure CLI

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)
![Build Status](https://dev.azure.com/azureiotdevxp/aziotcli/_apis/build/status/Merge%20-%20Azure.azure-iot-cli-extension?branchName=dev)

The **Azure IoT extension for Azure CLI** aims to accelerate the development, management and automation of Azure IoT solutions. It does this via addition of rich features and functionality to the official [Azure CLI](https://docs.microsoft.com/en-us/cli/azure).

## News

- ❗ When upgrading your Azure CLI core version, for the best experience and to avoid breaking changes, we recommend updating your `azure-iot` extension to the [latest available](https://github.com/Azure/azure-iot-cli-extension/releases).

- Azure CLI `2.24.0` requires an `azure-iot` extension update to `0.10.11` or later for IoT Hub commands to work properly. However **we recommend** at least `azure-iot` `0.10.14`. Updating the extension can be done with `az extension update --name azure-iot`.

> Note: A common error that arises when using an older `azure-iot` with Azure CLI `2.24.0+` shows as follows: `AttributeError: 'IotHubResourceOperations' object has no attribute 'config'`.

- Starting with version `0.10.13` of the IoT extension, you will need an Azure CLI core version of `2.17.1` or higher. IoT extension version `0.10.11` remains on the extension index to support environments that cannot upgrade core CLI versions.

- The legacy IoT extension Id `azure-cli-iot-ext` is deprecated in favor of the new modern Id `azure-iot`. `azure-iot` is a superset of `azure-cli-iot-ext` and any new features or fixes will apply to `azure-iot` only. Also the legacy and modern IoT extension should **never** co-exist in the same CLI environment.

    Uninstall the legacy extension with the following command: `az extension remove --name azure-cli-iot-ext`.

    Related - if you see an error with a stacktrace similar to:

    ```text
    ...
    azure-cli-iot-ext/azext_iot/common/_azure.py, ln 90, in get_iot_hub_connection_string
        client = iot_hub_service_factory(cmd.cli_ctx)
    cliextensions/azure-cli-iot-ext/azext_iot/_factory.py, ln 29, in iot_hub_service_factory
        from azure.mgmt.iothub.iot_hub_client import IotHubClient
    ModuleNotFoundError: No module named 'azure.mgmt.iothub.iot_hub_client'
    ```

    The resolution is to remove the deprecated `azure-cli-iot-ext` and install any version of the `azure-iot` extension.

## Commands

Please refer to the official `az iot` reference on [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/ext/azure-iot/iot) for a complete list of supported commands.  You can also find IoT CLI usage tips on the [wiki](https://github.com/Azure/azure-iot-cli-extension/wiki/Tips).

## Installation

1. Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
    - You must have at least `v2.32.0` for the latest versions of `azure-iot`, which you can verify with `az --version`
1. Add, Update or Remove the IoT extension with the following commands:
    - Add: `az extension add --name azure-iot`
    - Update: `az extension update --name azure-iot`
    - Remove: `az extension remove --name azure-iot`

Please refer to the [Installation Troubleshooting Guide](docs/install-help.md) if you run into any issues or the [Alternative Installation Methods](docs/alt-install-methods.md) if you'd like to install from a GitHub release or local source.

## Usage

After installing the Azure IoT extension your CLI environment is augmented with the addition of `hub`, `central`, `dps`, `dt`, `edge` and `device` commands.

For usage and help content of any command or command group, pass in the `-h` parameter. Root command group details are shown for the following IoT services.

> **Click** a section to expand or collapse

<details open>
  <summary>Digital Twins</summary>

```text
$ az dt -h

Group
    az dt : Manage Azure Digital Twins solutions & infrastructure.

Subgroups:
    data-history    : Manage and configure data history.
    endpoint        : Manage and configure Digital Twins instance endpoints.
    job             : Manage and configure jobs for a digital twin instance.
    model           : Manage DTDL models and definitions on a Digital Twins instance.
    network         : Manage Digital Twins network configuration including private links and
                      endpoint connections.
    role-assignment : Manage RBAC role assignments for a Digital Twins instance.
    route           : Manage and configure event routes.
    twin            : Manage and configure the digital twins of a Digital Twins instance.

Commands:
    create          : Create or update a Digital Twins instance.
    delete          : Delete an existing Digital Twins instance.
    list            : List the collection of Digital Twins instances by subscription or resource
                      group.
    reset [Preview] : Reset an existing Digital Twins instance by deleting associated
                      assets. Currently only supports deleting models and twins.
    show            : Show an existing Digital Twins instance.
    wait            : Wait until an operation on an Digital Twins instance is complete.
```

</details>

<details>
  <summary>IoT Central</summary>

```text
$ az iot central -h

Group
    az iot central : Manage IoT Central resources.
        IoT Central is an IoT application platform that reduces the burden and cost of developing,
        managing, and maintaining enterprise-grade IoT solutions. Choosing to build with IoT Central
        gives you the opportunity to focus time, money, and energy on transforming your business
        with IoT data, rather than just maintaining and updating a complex and continually evolving
        IoT infrastructure.

        IoT Central documentation is available at https://aka.ms/iotcentral-documentation
        Additional information on CLI commands is available at https://aka.ms/azure-cli-iot-ext.

Subgroups:
    api-token             : Manage API tokens for your IoT Central application.
    app                   : Manage IoT Central applications.
    device                : Manage and configure IoT Central devices.
    device-group          : Manage and configure IoT Central device groups.
    device-template       : Manage and configure IoT Central device templates.
    diagnostics [Preview] : Perform application and device level diagnostics.
    enrollment-group      : Manage and configure IoT Central enrollment group.
    export      [Preview] : Manage and configure IoT Central data exports.
    file-upload-config    : Manage and configure IoT Central file upload.
    job                   : Manage and configure jobs for an IoT Central application.
    organization          : Manage and configure organizations for an IoT Central application.      
    role                  : Manage and configure roles for an IoT Central application.
    scheduled-job         : Manage and configure IoT Central schedule job.
    user                  : Manage and configure IoT Central users.

Commands:
    query       [Preview] : Query device telemetry or property data with IoT Central Query
                            Language.
```

</details>

<details>
  <summary>IoT Device Provisioning</summary>

```text
$ az iot dps -h

Group
    az iot dps : Manage entities in an Azure IoT Hub Device Provisioning Service (DPS). Augmented
    with the IoT extension.

Subgroups:
    access-policy     : Manage Azure IoT Hub Device Provisioning Service access policies.
    certificate       : Manage Azure IoT Hub Device Provisioning Service certificates.
    connection-string : Manage connection strings for an Azure IoT Hub Device Provisioning Service
                        instance.
    enrollment        : Manage individual device enrollments in an Azure IoT Hub Device Provisioning
                        Service.
    enrollment-group  : Manage enrollment groups in an Azure IoT Hub Device Provisioning Service.
    linked-hub        : Manage Azure IoT Hub Device Provisioning Service linked IoT hubs.

Commands:
    create            : Create an Azure IoT Hub device provisioning service.
    delete            : Delete an Azure IoT Hub device provisioning service.
    list              : List Azure IoT Hub device provisioning services.
    show              : Get the details of an Azure IoT Hub device provisioning service.
    update            : Update an Azure IoT Hub device provisioning service.
```

</details>

<details>
  <summary>IoT Edge</summary>

```text
$ az iot edge -h

Group
    az iot edge : Manage IoT solutions on the Edge.

Subgroups:
    deployment  : Manage IoT Edge deployments at scale.

Commands:
    set-modules : Set edge modules on a single device.
```

</details>

<details open>
  <summary>IoT Hub</summary>

```text
$ az iot hub -h

Group
    az iot hub : Manage entities in an Azure IoT Hub.

Subgroups:
    certificate                         : Manage IoT Hub certificates.
    configuration                       : Manage IoT automatic device management configuration at
                                          scale.
    connection-string                   : Manage IoT Hub connection strings.
    consumer-group                      : Manage the event hub consumer groups of an IoT hub.
    device-identity                     : Manage IoT devices.
    device-twin                         : Manage IoT device twin configuration.
    devicestream                        : Manage device streams of an IoT hub.
    digital-twin                        : Manipulate and interact with the digital twin of an IoT
                                          Hub device.
    distributed-tracing       [Preview] : Manage distributed settings per-device.
    identity                            : Manage identities of an Azure IoT hub.
    job                                 : Manage IoT Hub jobs (v2).
    message-enrichment                  : Manage message enrichments for endpoints of an IoT Hub.
    module-identity                     : Manage IoT device modules.
    module-twin                         : Manage IoT device module twin configuration.
    policy                              : Manage shared access policies of an IoT hub.
    route                               : Manage routes of an IoT hub.
    routing-endpoint                    : Manage custom endpoints of an IoT hub.

Commands:
    create                              : Create an Azure IoT hub.
    delete                              : Delete an IoT hub.
    generate-sas-token                  : Generate a SAS token for a target IoT Hub, device or
                                          module.
    invoke-device-method                : Invoke a device method.
    invoke-module-method                : Invoke a module method.
    list                                : List IoT hubs.
    list-skus                           : List available pricing tiers.
    manual-failover                     : Initiate a manual failover for the IoT Hub to the geo-
                                          paired disaster recovery region.
    monitor-events                      : Monitor device telemetry & messages sent to an IoT Hub.
    monitor-feedback                    : Monitor feedback sent by devices to acknowledge cloud-to-
                                          device (C2D) messages.
    query                               : Query an IoT Hub using a powerful SQL-like language.
    show                                : Get the details of an IoT hub.
    show-connection-string [Deprecated] : Show the connection strings for an IoT hub.
    show-quota-metrics                  : Get the quota metrics for an IoT hub.
    show-stats                          : Get the statistics for an IoT hub.
    update                              : Update metadata for an IoT hub.
```

</details>

<details open>
  <summary>Device Update for IoT Hub</summary>

```text
$ az iot du -h

Group
    az iot du : Device Update for IoT Hub is a service that enables you to deploy over-the-air
    updates (OTA) for your IoT devices.
        As organizations look to further enable productivity and operational efficiency, Internet of
        Things (IoT) solutions continue to be adopted at increasing rates. This makes it essential
        that the devices forming these solutions are built on a foundation of reliability and
        security and are easy to connect and manage at scale. Device Update for IoT Hub is an end-
        to-end platform that customers can use to publish, distribute, and manage over-the-air
        updates for everything from tiny sensors to gateway-level devices.
        To learn more about the Device Update for IoT Hub service visit
        https://docs.microsoft.com/en-us/azure/iot-hub-device-update/.

Subgroups:
    account  : Device Update account management.
    device   : Device Update device management.
    instance : Device Update instance management.
    update   : Device Update update management.
```

</details>

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
