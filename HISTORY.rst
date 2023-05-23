.. :changelog:

Release History
===============


unreleased
+++++++++++++++

0.21.2
+++++++++++++++

**IoT Hub updates**

* Fixed issue where `az iot hub monitor-events` would hang when message payload cannot be decoded as unicode.
* `az iot hub state migrate` will now use the origin IoT Hub's resource group when the destination IoT Hub's resource group is not given.

**IoT device updates**

* `az iot device send-d2c-message` and `az iot device c2d-message send` now support providing message data from a file using the `--data-file-path` argument.
* `az iot device c2d-message receive` will now show a warning, along with other event properties, if the message payload cannot be decoded.

**IoT Product**

* Deprecation of `az iot product`. This command group will be removed in a future release.

**IoT Edge Deployment**

* Fixed the documentation issue where the `--layered` parameter's description incorrectly mentioned `This option is an alias for --no-validation.`.

0.21.1
+++++++++++++++

**IoT Hub updates**

* Improved help for `az iot edge deployment create` to better describe layered deployments.

* The command `az iot edge export-modules` is now GA.


0.21.0
+++++++++++++++

**General updates**

* The Azure IoT CLI extension min core CLI version incremented to `2.37.0`.

**Digital Twins updates**

* Fix to ensure policy key retreival during Digital Twin endpoint creation works. Affected commands are:  - `az dt endpoint create *`.

* Addition of new temporary experimental parameter `--max-models-per-batch` for `az dt model create` to let user adjust batch size when directory exceeds
  250 models.


0.20.0
+++++++++++++++

**IoT Hub updates**

* Addition of the `az iot hub state` command group which introduces commands to save, upload, and copy states between IoT Hubs. This will
  allow for easier migration of IoT Hubs when changing location, IoT Hub SKU, number of Event Hub partitions and more.
  For more information, please read the trouble shooting guide [here](https://aka.ms/aziotcli-iot-hub-state).

  The commands are as follows:

  - `az iot hub state export` to save the current state of an IoT Hub to a JSON file.
  - `az iot hub state import` to upload a state from a JSON file to an IoT Hub.
  - `az iot hub state migrate` to copy a state of an IoT Hub to another IoT Hub.

**Digital Twins updates**

* The Digital Twin controlplane commands will now use the newest API 2023-01-31. The following command groups are affected:
 - `az dt create`, `az dt delete`, `az dt list`, `az dt reset`, `az dt show`, `az dt wait`
 - `az dt data-history`
 - `az dt endpoint`
 - `az dt identity`
 - `az dt network`
 - `az dt route`

* Added new options for creating a data history connection and deleting one. The create command, `az dt data-history connection create adx`,
  now supports adding two separate tables for relationship lifecycle events and twin lifecycle events, recording property and item removals,
  and adding the new default for the generic table name (now known as property event table). The delete command,
  `az dt data-history connection delete`, now supports a clean parameter which will do a best-effort attempt to clean connection creation artifacts.


0.19.1
+++++++++++++++

**IoT Hub updates**

* Addition of export modules command for edge device

  - az iot edge export-modules

**Digital Twins updates**

* Digital Twins dataplane commands now use the newer 2023-02-27-preview API. The following command groups are affected:
 - `az dt model`
 - `az dt twin`
 - `az dt job`

* `az dt job import` now supports newer job statuses, including "cancelling" and "cancelled". Now, to delete a running job, the job must be first cancelled with `az dt job import cancel`.


0.19.0
+++++++++++++++

**IoT Hub updates**

* Addition of `az iot hub message-endpoint` and `az iot hub message-route` commands, which function similarly to
  existing `az iot hub routing-endpoint` and  `az iot hub route` commands respectively. These new commands will
  use the newer IoT Hub Service API (2022-04-30-preview) if the Azure CLI supports it (min version 2.43.0). If the
  Azure CLI is not updated, the older API version will be used. A new endpoint type, Cosmos DB Containers is added
  with the newer API. Most of the command and parameter structure is the same, except for creation of endpoints,
  in which the type is specified in the command as so:

- az iot hub message-endpoint create cosmosdb-container
  * Hidden if the Azure CLI version does not support it.
- az iot hub message-endpoint create eventhub
- az iot hub message-endpoint create servicebus-queue
- az iot hub message-endpoint create servicebus-topic
- az iot hub message-endpoint create storage-container

Other notable changes, which are not affected by API versions, include:

* Addition of fallback route management through `az iot hub message-route fallback set` and
  `az iot hub message-route fallback show`

* Modification of how route testing works for testing all route sources. If `az iot hub message-route test` is called
  without specifying a route name or type, all types will be tested rather than only DeviceMessage routes.

* Addition of new parameters `--custom-labels` and `--custom-metrics` for `az iot hub configuration create` and
  `az iot edge deployment create` to let user input labels and metrics in key=value pair format.

**Digital Twins updates**

* Addition of User Assigned Identities for data history connections. The command `az dt data-history connection create adx`
  now can take an extra parameter `--mi-user-assigned` to use an associated User Assigned Identity for the connection
  creation rather than the system assigned identity for the Digital Twin.
* Some minor improvements to command documentation involving managed identities.

**IoT Edge updates**

* Introduces a new experimental command `az iot edge devices create` that enables advanced IoT Edge device creation and configuration.
  This command allows users to specify either multiple inline arguments (`--device property=value`) or a [configuration file](https://aka.ms/aziotcli-edge-devices-config)
  to create multiple edge devices (including nested device scenarios) and configure their deployments.

  If an output path is specified, this command will also create tar files containing each device's certificate bundle, an IoT Edge
  `config.toml` config file and an installation script to configure a target Edge device with these settings.

**IoT DPS updates**

* Removed file extension restriction for attached certificates in individual enrollments and enrollment groups creation/update commands,
  and added suggested certificate format in `--help` docs.

**Device Update**

* Refactored file hash operations for better performance and to overcome Windows 32-bit process memory constraints.
* Removed import manifest schema upper limit of file size in bytes.


0.18.3
+++++++++++++++

**IoT Hub updates**

* The root-authority migration feature is now available. Since the Baltimore root will soon expire, IoT Hub will
  transition to the DigiCert Global G2 root starting February 15, 2023. You will need to update all device certificates
  to use the new G2 root.

  **These commands are temporary** and will be removed once all IoT Hubs have been transitioned:

  - az iot hub certificate root-authority show
  - az iot hub certificate root-authority set

  To learn more about this transition, visit http://aka.ms/iot-ca-updates/.

**IoT Central updates**

* Fixed an issue with enrollement group certificate encoding



0.18.2
+++++++++++++++

**Device Update**

`az iot du update init v5` improvements:

* Fixed an issue where duplicate `files[]` / `relatedFiles[]` entries were created via multiple usage of --file or
  --related-file against the same update file asset.
* If the inline step content handler requires `handlerProperties.installedCriteria` and a value was not provided,
  a default value will be automatically added with a warning.
* If the inline step content handler starts with 'microsoft' (case-insensitive), valid first-party handler values
  will be enforced.
* Inline json rules and examples provided for every shell.
* Improves error handling for free-form json properties.

**Digital Twins**

* New command group `az dt identity` to easily manage instance identities.
* `az dt create` supports adding user-managed identities on create.
* `az dt endpoint create <type>` commands support identity parameters - you are able to leverage managed identities
  to integrate with the target endpoint.
  * The `eventgrid` endpoint does not support managed identities.
* Resource group for endpoint resources are no longer required - if not present, the resource group of the
  digital twins instance is used.


0.18.1
+++++++++++++++

**Device Update**

* Removed preview classification from the root Azure Device Update command group.
  Commands are GA with the exception of `az iot du update stage` and `az iot du update init` which are still preview.


0.18.0
+++++++++++++++

**IoT Hub updates**

* **[Breaking Change]** The `az iot hub device-identity export` and `az iot hub device-identity import` commands have been migrated to use IoT Hub APIs instead of ARM.
* **[Breaking Change]** Device identity export/import commands now expect the parameter `--auth-type` to specify the IoT Hub API data access auth type (instead of storage access auth type).
* Updated the IoT Hub service SDK to now use the newer `2021-04-12` API version.
* Device identity export/import commands now support optional parameters for storage account and blob container names - users no longer need to supply input/output Blob container SAS URIs.
* Device identity export/import commands now automatically derive storage auth type - hence the parameter `storage_authentication_type` has been deprecated.
* Adds `az iot hub device-twin list` as a highly recommended alternative to `az iot hub device-identity list`.
  Functionality remains the same as both return a list of device twins and `az iot hub device-identity list` may be altered or deprecated in the future.

**Device Update**

* The in-preview Azure Device Update CLI root namespace changed from `az iot device-update` to `az iot du`.
* The in-preview `az iot device-update update init calculate-hash` command moved to `az iot du update calculate-hash`.
* Introducing the preview `az iot du update stage` command. The update stage command is designed to automate
  the pre-requisite steps of importing an update. Read the command reference to learn more.

**General updates**

* The Azure IoT CLI extension min core CLI version incremented to `2.32.0`.


0.17.3
+++++++++++++++

**Device Update**

* Adds `az iot device-update update init calculate-hash`, a utility command used to calculate the base64 hash representation of one or more files.
* The `update init v5` command will by default validate the generated import manifest using the official json schema definition. Client-side validation can be skipped by using `--no-validation`.
* The `update init v5` command support level has changed from `experimental` to `preview`.

**IoT Central updates**

* `--api-version` parameter will be deprecated and ignored. The IoT Central API will alway call latest GA version or latest preview version (if any API only exists in preview).

* Add support for enrollment groups CRUD.

  - az iot central enrollment-group

    - az iot central enrollment-group list
    - az iot central enrollment-group show
    - az iot central enrollment-group create
    - az iot central enrollment-group delete
    - az iot central enrollment-group update
    - az iot central enrollment-group verify-certificate
    - az iot central enrollment-group generate-verification-code

* Add support for scheduled jobs CRUD.

  - az iot central scheduled-job

    - az iot central scheduled-job list
    - az iot central scheduled-job show
    - az iot central scheduled-job create
    - az iot central scheduled-job delete
    - az iot central scheduled-job update
    - az iot central scheduled-job list-runs


0.17.2
+++++++++++++++

**General Updates**

* Hotfix for ensuring the global subscription parameter (`--subscription`) passes through sub-commands. Affected commands include:

  - az dt create
  - az dt job import
  - az iot device-update account create


0.17.1
+++++++++++++++

**Device Update**

* The Device Update control plane (or infrastructure related) command groups `az iot device-update account` and
  `az iot device-update instance` now use the GA API version of 2022-10-01.
* The Device Update data plane command groups `az iot device-update device` and
  `az iot device-update update` now use the GA API version of 2022-10-01.
* The command `az iot device-update device class list` adds support for `--filter` when no `--group-id` is provided.
* The parameters `--account`, `--instance`, and `--resource-group` support setting default overridable values via config.
  Use `az config set` i.e. `az config set defaults.adu_account=<name>` or `az configure` i.e. `az configure --defaults adu_account=<name>`.
* Introducing the experimental command `az iot device-update update init v5` for initializing (or generating) an import manifest
  with the desired state.
* Improved built-in documentation.


0.17.0
+++++++++++++++

**Device Update**

* The Device Update command group supports all data plane functionality via **in-preview** `update` and `device`
  sub-command groups. The data plane API version used is 2022-07-01-preview.

**IoT Hub updates**

* Updated the `az iot hub monitor-events` command to support an optional `--message-count` argument.
  The message-count defines the maximum number of messages received from the hub before the monitor automatically stops.
  If not provided the monitor keeps running until the user force-kills the monitor.


0.16.1
+++++++++++++++

* Fix issue preventing reference docgen.


0.16.0
+++++++++++++++

**Device Update**

* The **in preview** `az iot device-update` command group is now always available.
  No environment variable is needed for activation.

  - The Device Update command group supports all `account` and `instance` related functionality against
    control plane API version 2022-04-01-preview.

**Digital Twin updates**

* Updated `az dt model create` command to process input ontologies larger than 250 models in a single command run.
  Size of input ontology is only constrained by the maximum number of models(default 10000) a DT instance can store.

**IoT Central updates**

* Add support for device groups CRUD.

  - az iot central device-group

    - az iot central device-group list
    - az iot central device-group show
    - az iot central device-group create
    - az iot central device-group delete
    - az iot central device-group update

* Add support for device attestation CRUD.

  - az iot central device attestation

    - az iot central device attestation show
    - az iot central device attestation create
    - az iot central device attestation delete
    - az iot central device attestation update

* Add support for device/module properties/telemetry/command.

  - az iot central device list-components
  - az iot central device list-modules
  - az iot central device telemetry

    - az iot central device telemetry show

  - az iot central device twin

    - az iot central device twin show
    - az iot central device twin update
    - az iot central device twin replace

* Add support for 2022-05-31 GA version.

  - az iot central api-token
  - az iot central device-template
  - az iot central device-group
  - az iot central device
  - az iot central file-upload-config
  - az iot central organization
  - az iot central role
  - az iot central user

**IoT device updates**

* `az iot device simulate` and `az iot device send-d2c-message` support a `--model-id` argument.
  The model Id is used by a device to advertise the digital twin interface it implements.


0.15.0
+++++++++++++++

**General updates**

* Dropped support for Python 3.6. The IoT extension is constrained to Python 3.7 or greater.
  If for whatever reason you cannot upgrade from 3.6 you are able to use older extension versions.

**Device Update**

* Introducing the **in preview** Azure Device Update for IoT Hub root command group `az iot device-update`.
  To learn more about the service visit https://docs.microsoft.com/en-us/azure/iot-hub-device-update/.

  - This command group is behind a feature flag environment variable. Set `IOT_CLI_ADU_ENABLED` to any value
    to activate the command group.
  - The Device Update command group supports all `account` and `instance` related functionality against
    control plane API version 2022-04-01-preview.

**IoT device updates**

* Added device registration commands, `az iot device registration create` to register a device to an individual
  enrollment or an enrollment group. Currently, devices with symmetric key and x509 certificate authentication
  are supported. Once registered, the device will show up in the linked IoT Hub and can be interacted with or
  simulated using other `az iot device` commands.

* Added support for simulating device identities that use x509 thumbprint or CA authentication, impacting the
  following commands:
    - `az iot device simulate`
    - `az iot device send-d2c-message`

**Digital Twin updates**

* Added `az dt job import` command group, which will allow users to create and manage jobs for bulk importing
  models, twins and relationships to a Digital Twins instance. The bulk import data must be stored as a blob in
  a user owned storage account and container.

* Data History commands, under the `az dt data-history` command group, are now GA.


0.14.1
+++++++++++++++

**IoT Hub updates**

* Updated creation for self-signed certificates to use the Cryptography library instead of the PyOpenSSL library.

**IoT DPS updates**

* Added registration commands for individual enrollment groups:

    - az iot dps enrollment registration show
    - az iot dps enrollment registration delete

**IoT Device Certification**

* Updated service API endpoint to vNext URL.


0.14.0
+++++++++++++++

**General updates**

* The generic CLIErrors raised across the extension have been changed to more specific semantically correct exceptions aligning with CLI core.
* Fix for issue #475 resolving `sys.excepthook` upon terminating monitor-events process in Py 3.9+ environments [IoT Hub, IoT Central].

**Digital Twin updates**

* Added optional `--telemetry-source-time` parameter to `az dt twin telemetry send` to allow users to
  add a custom timestamp to the sent telemetry.

* Updated both controlplane and dataplane SDKs to now use the newer 2021-06-30-preview API version.

* Added `--no-wait` parameter to the following functions:

  - az dt create
  - az dt endpoint create
  - az dt private-endpoint create

* Added `az dt data-history` command group, which will allow users to configure a data history connection
  for a Digital Twins instance using an Event Hub and Azure Data Explorer database. Once configured,
  changes to the Digital Twins instance can be seen in the Azure Data Explorer database.

**IoT Central updates**

* Added commands for Edge devices and modules:
  - az iot central device edge module
    - az iot central device edge module list
    - az iot central device edge module restart
    - az iot central device edge module show

  - az iot central device edge manifest
    - az iot central device edge manifest show

  - az iot central device edge children
    - az iot central device edge children list
    - az iot central device edge children add
    - az iot central device edge children remove

**IoT DPS updates**

* Reorganizing command structure for enrollment-group commands:
  - 'az iot dps compute-device-key' is deprecated use 'az iot dps enrollment-group compute-device-key' instead.
  - 'az iot dps registration' is deprecated use 'az iot dps enrollment-group registration' instead.
  - 'az iot dps registration delete' is deprecated use 'az iot dps enrollment-group registration delete' instead.
  - 'az iot dps registration list' is deprecated use 'az iot dps enrollment-group registration list' instead.
  - 'az iot dps registration show' is deprecated use 'az iot dps enrollment-group registration show' instead.


0.13.0
+++++++++++++++

**IoT Central updates**

* Added missing "update" sub-commands for all commands supporting it:

  - az iot central device update
  - az iot central device-template update
  - az iot central file-upload-config update
  - az iot central organization update
  - az iot central user update

* Added "compact" mode for "az iot central device-template list" command:
  When "-c" flag is passed, only Ids, display names and model types will be shown for the templates in the application.

* Added `az iot central device c2d-message purge` to purge cloud-to-device message queue

**IoT DPS updates**

* Added RBAC support for DPS dataplane commands, similar to the RBAC support for IoT Hub.
  The type of auth used to execute commands can be controlled with the "--auth-type" parameter
  which accepts the values "key" or "login". The value of "key" is set by default.

  * When "--auth-type" has the value of "key", like before the CLI will auto-discover
    a suitable policy when interacting with DPS.
  * When "--auth-type" has the value "login", an access token from the Azure CLI logged in principal
    will be used for the operation.

  * The following commands currently support `--auth-type`:

    * az iot dps enrollment
    * az iot dps enrollment-group
    * az iot dps registration

* Update DPS dataplane SDK to use the newer 2021-10-01 API version. Most command
  functionality has not changed. Updated commands include:

  - `az iot dps enrollment create` and `az iot dps enrollment update` support
    optional device information via `--device-info`


0.12.1
+++++++++++++++

**IoT DPS updates**

* Resolves issue where usage of `--login` with connection string still required `az login`.


0.12.0
+++++++++++++++

**IoT Central updates**

* Fixed iot hub token leak for device twin show

* Adds new preview commands (v1.1-preview)

  - Query (az iot central query)
  - Destination (az iot central export destination)
  - Export (az iot central export)

**General Updates**

* The IoT extension officially supports Python 3.10.

**IoT DPS updates**

* Added `az iot dps connection-string show` to show the DPS connection string with
  similar support as the IoT Hub connection string show.

* DPS support DPS connection string as a resource identifier with the --login or -l
  parameter, similar to IoT Hub Identifier Arguments.

* DPS now supports auto resource and policy discovery. Resource group is no longer a
  required parameter for az iot dps dataplane commands. Auto policy discovery ensures
  that a policy with all the correct permissions is available and is used by the IoT
  extension for all DPS operations.

* `az iot dps compute-device-key` now supports enrollment group identifiers in addition to
  enrollment group symmetric key. Please take a look at the `--help` docs for functionality
  and usage highlights.

* Improvement to help documentation for DPS functions.

**IoT Hub updates**

* `az iot hub device-identity create` supports a device scope argument via `--device-scope` parameter.

0.11.0
+++++++++++++++

**IoT Central updates**

* Adds preview commands (v1.1-preview):

  - Organizations (az iot central organization)
  - File Upload Configuration (az iot central file-upload-config)
  - Jobs (az iot central job)
* Adds x-ms-client-request-id header for each request

**Breaking Changes**

* List commands like `az iot central device list` and others,
  now return list of items instead of a main dict with item ids as keys and items as values.

  Involved commands:
   - az iot central device list
   - az iot central device-template list
   - az iot central api-token list
   - az iot central user list

0.10.17
+++++++++++++++

**IoT Hub updates**

* Fixed an issue in 0.10.16 causing IoT Hub command failure in Windows MSI environment.

0.10.16
+++++++++++++++

**IoT Central updates**

* Adds support for listing devices.
* Adds support for listing device templates.

**IoT Hub updates**

* Device simulation overhaul ("az iot device simulate"). Device simulation is experimental and subject to change.
  Please take a look at the --help docs for functionality and usage highlights.
* Device and module identity creation support usage of custom symmetric keys.

0.10.15
+++++++++++++++

**IoT Central updates**

* Adds support for listing device groups
* Adds support for listing roles and get role by id

0.10.14
+++++++++++++++

**IoT Central updates**

* Adds support to run root/interface level device commands.
* Adds support to get command history for root/interface level device commands.
* The --interface-id parameter for commands "device command run" , "device command history" changed to optional.

**IoT Hub updates**

* Fix for "az iot hub c2d-message receive" - the command will use the "ContentEncoding" header value (which indicates the message body encoding)
  or fallback to utf-8 to decode the received message body.

* Addition for "az iot hub generate-sas-token" - the command will allow offline generation of a SAS Token using a connection string.

* Changes to Edge validation for set-modules and edge deployment creation:

  By default only properties of system modules $edgeAgent and $edgeHub are validated against schemas installed with the IoT extension.
  This can be disabled by using the --no-validation switch.

**Azure Digital Twins updates**

* Addition of the following commands

  * az dt reset - Preview command which deletes all data entities from the target instance (models, twins, twin relationships).


0.10.13
+++++++++++++++

**General updates**

* Min CLI core version raised to 2.17.1


0.10.12
+++++++++++++++

**IoT Central updates**

* Public API GA update

  * Remove preview tag for  api-token, device, device-template, user routes. Default routes use central GA API's.
  * Add support for preview and 1.0 routes.
  * Addition of the optional '--av' argument to specify the version of API for the requested operation.

**IoT Hub updates**

* Removed deprecated edge offline commands and artifacts.
* Removed deprecated device-identity | module-identity show-connection-string commands.

* Most commands against IoT Hub support Azure AD based access. The type of auth
  used to execute commands can be controlled with the "--auth-type" parameter
  which accepts the values "key" or "login". The value of "key" is set by default.

  * When "--auth-type" has the value of "key", like before the CLI will auto-discover
    a suitable policy when interacting with iothub.
  * When "--auth-type" has the value "login", an access token from the Azure CLI logged in principal
    will be used for the operation.

  * The following commands currently remain with key based access only.

    * az iot hub monitor-events
    * az iot device c2d-message receive
    * az iot device c2d-message complete
    * az iot device c2d-message abandon
    * az iot device c2d-message reject
    * az iot device c2d-message purge
    * az iot device send-d2c-message
    * az iot device simulate

For more information about IoT Hub support for AAD visit: https://docs.microsoft.com/en-us/azure/iot-hub/iot-hub-dev-guide-azure-ad-rbac

**Azure Digital Twins updates**

* Addition of the following commands

  * az dt model delete-all - Deletes all models associated with the Digital Twins instance.


0.10.11
+++++++++++++++

**IoT Hub updates**

* Fixed an issue where an explicit json null could not be sent for the following commands:

  * az iot hub invoke-device-method
  * az iot hub invoke-module-method

* When using "az iot hub connection-string show" against all hubs in a group or subscription, the command will now
  show a warning instead of raising an error if a problem occurs obtaining a connection-string from a particular hub.

**Azure Digital Twins updates**

* Addition of the following commands

  * az dt twin delete-all - Deletes all digital twins within a Digital Twins instance.
  * az dt twin relationship delete-all - Deletes all digital twin relationships within a Digital Twins instance

* Fixed an issue in the following update commands where malformed json patch content would not raise an error
  causing the process to call the respective service endpoint with a request payload containing an empty array.

  * az dt twin update
  * az dt twin relationship update
  * az dt twin component update

**IoT Central updates**

* Addition of the following commands

  * az iot central device manual-failover - Execute a manual failover of device across multiple IoT Hubs
  * az iot central device manual-failback - Reverts the previously executed failover command by moving the device back to it's original IoT Hub

For more information about device high availability visit https://github.com/iot-for-all/iot-central-high-availability-clients#readme

0.10.10
+++++++++++++++

**Azure Digital Twins updates**

* Addition of the optional '--etag' argument for the following commands:

  * az dt twin [update | delete]
  * az dt twin relationship [update | delete]

* Addition of the optional '--if-not-match' switch for the following commands:

  * az dt twin create
  * az dt twin relationship create


0.10.9
+++++++++++++++

**Azure IoT Product Certification service updates**

* Fix bug for `az iot product test create` sending a byte string instead of "regular" base64 string.

**Azure Digital Twins updates**

* Addition of Digital Twins Identity support focused around Managed Service Identity (MSI) and Identity based endpoint integration.
* Addition of Digital Twins networking functionality around private-links and private-endpoint connections. See "az dt network".

**IoT Hub updates**

* Improve http debug logging.
* Fix bug related to issue #296. Adds a clause to device-identity update that allows user to update primary-key / secondary-key
  and primary-thumbprint / secondary-thumbprint values (respectively, per auth method) without needing to specify the auth_method in the update command.


0.10.8
+++++++++++++++

**IoT Central updates**

* az iot central device|device-template|api-token|diagnostic help strings updated with improved language.
* update parsing template logic to support  DTDLV2 models.
* remove deprecated commands  1) iot central app device-twin 2) iot central app monitor-events


**IoT Hub updates**

The following commands support an explicit etag parameter. If no etag arg is passed the value "*" is used.

* az iot hub device-identity update
* az iot hub device-identity delete
* az iot hub device-identity renew-key
* az iot hub device-twin update
* az iot hub device-twin delete
* az iot hub module-identity update
* az iot hub module-identity delete
* az iot hub module-twin update
* az iot hub module-twin delete
* az iot hub configuration update
* az iot hub configuration delete
* az iot edge deployment update
* az iot edge deployment update

Re-introduce prior in-preview IoT Hub device digital twin/pnp runtime commands under the "az iot hub digital-twin" root command group.

* az iot hub digital-twin show
* az iot hub digital-twin update
* az iot hub digital-twin invoke-command


0.10.7
+++++++++++++++

**IoT Hub updates**

* Change command name from az iot hub device-identity `regenerate-key` to `renew-key` to better align with az cli core verbs.


0.10.6
+++++++++++++++

**Azure IoT Product Certification service**

* Fix bug for `az iot product test create` not specifying query parameter "GenerateProvisioningConfiguration" appropriately.


**IoT Hub updates**

* SDK refresh. IoT Hub service calls point to api-version 2020-09-30.

* Updated nested edge (edge offline) commands to support parentScopes.

  Set of changes

  * 'az iot hub device-identity get-parent' is deprecated use 'az iot hub device-identity parent show' instead. Deprecated command group is planned to be removed by December 2021
  * 'az iot hub device-identity set-parent' is deprecated use 'az iot hub device-identity parent set' instead. Deprecated command is planned to be removed by December 2021
  * 'az iot hub device-identity add-children' is deprecated use 'az iot hub device-identity children add' instead. Deprecated command group is planned to be removed by December 2021
  * 'az iot hub device-identity remove-children' is deprecated use 'az iot hub device-identity children remove' instead. Deprecated command is planned to be removed by December 2021
  * 'az iot hub device-identity list-children' is deprecated use 'az iot hub device-identity children list' instead. Deprecated command group is planned to be removed by December 2021


0.10.5
+++++++++++++++

**Azure Digital Twins updates**

* Breaking change on the `--tags` parameter for `az dt create`. The prior input format of --tags "a=b;c=d" has been
  changed to  --tags a=b c=d to be more consistent with other Az CLI tag formats.


0.10.4
+++++++++++++++

**General updates**

* IoT extension installation constrained to Python 3.6 or greater.

**Azure Digital Twins updates**

* ADT GA updates and release.

**IoT Edge**

* Validation schema updated with $edgeHub 1.1 route option.
* Introduces `--no-validation` to skip client side schema based validation for edge deployment creation.


0.10.3
+++++++++++++++

**General updates**

* Python 3.5 support will soon be dropped corresponding with the official end of life date.
* Formal python requires constraint added to constrain installs to Py 3.5+.

**IoT Plug-and-Play updates**

* The in preview `az iot pnp` command group has been removed. PnP CLI functionality will be re-imagined at a future point in time.


0.10.2
+++++++++++++++

**IoT Hub updates**

* Adds `az iot hub device-identity regenerate-key`.


0.10.1
+++++++++++++++

**IoT Plug-and-Play updates**

* Regenerated PnP runtime SDK to API version 2020-09-30
* All `az iot pnp` commands still remain under preview and are subject to change or deletion.

**IoT Hub updates**

* All configuration/edge deployment list operations no longer have a default top. By default all configuration entities will be returned.
  Existing --top input should not be affected.


0.10.0
+++++++++++++++

**IoT Hub updates**

* Add convenience arguments for device update.

**IoT DPS updates**

* Added --show-keys argument to `dps enrollment show` and `dps enrollment-group show` to include full attestation information for symmetric key enrollments and enrollment groups
* Regenerated 2019-03-31 DPS Service SDK

**Breaking Changes**

* `az iot dps enrollment show` and `az iot dps enrollment-group show` now return raw service results instead of deserialized models.
  This means that some properties that were previously returned as `null` for these commands will no longer be returned, possibly causing a breaking change.


0.9.9
+++++++++++++++

**IoT DPS updates**

* Introduces 'az iot dps compute-device-key' preview command to generate derived device SAS key

**IoT Central updates**

* Introduces 'az iot central diagnostics' preview command group to perform application and device level diagnostics
* Introduces 'az iot central device compute-device-key' preview command to generate derived device SAS key

* This release involves a re-grouping of IoT Central commands.

  Set of changes for GA commands

  * 'az iot central app device-twin' is deprecated use 'az iot central device twin' instead. Deprecated command group is planned to be removed by December 2020
  * 'az iot central app monitor-events' is deprecated use 'az iot central diagnostics monitor-events' instead. Deprecated command is planned to be removed by December 2020

  Set of changes for preview commands

  * 'az iot central app device registration-summary' moved to 'az iot central diagnostics registration-summary'
  * 'az iot central app monitor-properties' moved to 'az iot central diagnostics monitor-properties'
  * 'az iot central app validate-messages' moved to 'az iot central diagnostics validate-messages'
  * 'az iot central app validate-properties' moved to 'az iot central diagnostics validate-properties'
  * 'az iot central diagnostics monitor-events' added to support deprecation of 'az iot central app monitor-events'
  * 'az iot central app device run-command' moved to 'az iot central device command run'
  * 'az iot central app device show-command-history' moved to 'az iot central device command history'
  * 'az iot central device twin' added to support deprecation of 'az iot central app device-twin' command group

**IoT Hub updates**

Cloud-to-Device message enhancements

* Introduced new `az iot device c2d-message purge` command to purge the message queue for a device.
* Added message ack arguments to `az iot c2d-message receive` to ack the message after it is received:

  * Options are `--complete`, `--abandon`, and `--reject`, and only one can be used per command.
  * `az iot device c2d-message receive` with no ack arguments remains unchanged and will not ack the message.

Edge device creation enhancements

* Enabled x509 certificate authentication types (`x509_thumbprint` and `x509_ca`) for edge device creation with `az iot hub device-identity create --ee`

Bug fixes

* Fixes issue #243 where providing a connection string via --login still required "az login".

**Digital Twins updates**

The following command groups support passing in a DT instance hostname directly.

  * az dt route
  * az dt model
  * az dt twin

* Like before, if an instance name is provided, the user subscription is first queried for the target instance to retrieve the hostname.
* If a hostname is provided, the subscription query is skipped and the provided value is used for subsequent interaction.


0.9.8
+++++++++++++++
General changes

* Starting with v0.9.8 of the IoT extension, the minCliCoreVersion has been bumped to 2.3.1. This sets a comfortable minimum desired experience we want for our users.

Introducing preview commands for the Azure IoT Product Certification service

* A new IoT root command group 'az iot product' has been added

  * Use 'az iot product requirement' to manage product certification requirements
  * Use 'az iot product test' to manage device tests for certification

    * The product test command group encompasses test cases, runs and tasks

IoT Central updates

* Introduces the 'az iot central app user' preview command group for managing application users and service principals
* Introduces the 'az iot central app api-token' preview command group for managing application api tokens
* Removal of deprecated command groups and commands

IoT Hub updates

* All "... show-connection-string" based commands are deprecated in favor of "... connection-string show" canonical Az CLI style.

  * The show connection string command for a target IoT Hub has moved to the IoT extension.
  * 'az iot hub connection-string show' supports a --default-eventhub flag which indicates the operation will construct a connection string for the default eventhub endpoint of the target IoT Hub.
* Export/Import device identity commands support reading blob container SAS URI's via file

Azure Digital Twins updates

* The 'location' argument for 'az dt create' is now optional. If no location is provided, the location of the target resource group is used.


0.9.7
+++++++++++++++
Refreshes commands for the Azure IoT Plug & Play summer refresh

* The existing Plug & Play preview commands across Azure CLI and the IoT extension have been removed and replaced with a completely new commands. If you still need the legacy preview experience, then you can leverage older versions of the CLI and extension.
* The new commands exist entirely in the extension with the following command groups:

  * az iot pnp repo ## For tenant repository configuration
  * az iot pnp model ## For managing repository models and related content
  * az iot pnp role-assignment ## For managing role assignments for model repo assets
  * az iot pnp twin ## For interacting with the digital twin of a Plug & Play device

Introduces new preview Azure IoT Central commands

* az iot central app monitor-properties
* az iot central app validate-properties
* az iot central app device run-command
* az iot central app device show-command-history
* az iot central app device show-credentials

Device Provisioning Service update

* DPS enrollments now support the custom allocation policy resolving issue #200

0.9.6
+++++++++++++++
* Fixes event monitor initialization issue.

0.9.5
+++++++++++++++
* IoT Hub commands now support dynamic privileged policy discovery. `iothubhowner` is no longer relied on. Instead any policy that has `RegistryWrite`, `ServiceConnect` and `DeviceConnect` permissions will be used.
* Monitoring commands (such as for `central` or `hub`) support module Id filter. Also it is more clear that an event comes from a module.
* Improved validation of central telemetry.
* Digital Twin endpoint create commands now support custom subscription options.

0.9.4
+++++++++++++++
Azure Digital Twins Public Preview - CLI release

Introducing 35 new commands in the following command groups:

* az dt
* az dt endpoint
* az dt model
* az dt role-assignment
* az dt route
* az dt twin
* az dt twin relationship
* az dt twin telemety

0.9.3
+++++++++++++++
* IoT Hub device identity import/export commands support usage via managed service identity using the --auth-type argument.

* Adds preview command group "az iot central app device"

  * Adds preview command "az iot central app device create"
  * Adds preview command "az iot central app device show"
  * Adds preview command "az iot central app device list"
  * Adds preview command "az iot central app device delete"
  * Adds preview command "az iot central app device registration-info"
  * Adds preview command "az iot central app device registration-summary"

* Adds preview command group "az iot central app device-template"

  * Adds preview command "az iot central app device-template create"
  * Adds preview command "az iot central app device-template show"
  * Adds preview command "az iot central app device-template list"
  * Adds preview command "az iot central app device-template delete"
  * Adds preview command "az iot central app device-template map"

* Changed how results are displayed in "az iot central app validate-messages"

Known issues

* The following preview commands will retrieve at most 25 results

  * az iot central app device list
  * az iot central app device-template list
  * az iot central app device-template map

0.9.2
+++++++++++++++
* Device and module twin update operations provide explicit patch arguments (--desired, --tags).
* Adds command "az iot central app validate-messages"
* Remove Py 2.7 support and remnants from setup manifest.
* Remove Py 3.4 support and remnants from setup manifest.

0.9.1
+++++++++++++++
* Adds edge configuration argument for creating or updating enrollment[groups]

0.9.0
+++++++++++++++
* Breaking change: Evaluating an edge deployment/hub configuration SYSTEM metric (via show-metric) will return non-manipulated query output.
  This means the result is always a collection of objects.
* Breaking change: (second attempt) Remove long since deprecated parameter `--config-id` from edge deployments.
  Use `--deployment-id` or `-d` instead.
* When creating ADM module configurations, the target condition starting with 'from devices.modules where' is enforced.
* SDK refresh. IoT Hub service calls (except for 'az iot dt' commands) point to api-version 2019-10-01.
* Extension package name has been changed to 'azure-iot'.
* Help text for ADM module configurations has been updated with proper target condition syntax for module criteria.

0.8.9
+++++++++++++++
* Updated uamqp version to ~1.2.
* Simplified out-of-band dependency installation message.
* If uamqp installation fails the error is raised on stderr rather than having to use --debug.
* amqp frame traces are not shown when --debug is passed in to event monitoring.
* Fixed monitor-events not raising an exception if receiver client runs into an error.

0.8.8
+++++++++++++++
* Adds Jobs v2 command set.

0.8.7
+++++++++++++++
* Support IoT Edge layered deployments.
* Support ADM module twin definitions.
* Improved json schema validation error handling for edge deployments.
* Update top maximum for hub config/edge deployment list to 100.
* Breaking Change: Metric evaluation between hub configurations and edge deployments via show-metric work exactly the same.
* Breaking Change: New result format for `az iot device c2d-message receive`. The command now shows all properties.
* Updated IoT Central commands to allow the API for token collection to be overridden.
* `az iot device c2d-message send` supports sending all settable system properties per message.
* Updated uAMQP version range.
* Add user agent for MQTT & AMQP operations.
* Add QoS argument for `send-d2c-message`.

0.8.6
+++++++++++++++
* For IoT Hub commands - improves json handling for arguments that require json.
* Edge deployments support metric definitions at creation time (like device configurations)
* Fixes issue with `az iot hub invoke-device-method` preventing primitive value payloads.
* The `az iot device simulate` command will send default values for content-type and content-encoding. These values can be overridden.

0.8.5
+++++++++++++++
* Re-adds deprecated parameter --config-id to edge related commands. Note: --deployment-id/-d are the proper parameters to use in place of config-id when using edge deployment related commands.

0.8.4
+++++++++++++++
* Device simulate now supports sending arbitrary message properties (like in send-d2c-message).
* The preview dt monitor events command has been simplified. It works the same as vanilla iot hub monitoring but filters dt events and allows filtering by interface.
* Help content improvements.
* Remove long since deprecated parameter `--config-id` from edge deployments.

0.8.3
+++++++++++++++
* Removes long since deprecated command `az iot hub apply-configuration`.
* Resolve issue #100.
* Improve help content for `az iot edge deployment update` to explicitly show what can be updated.
* Fix message annotation used to filter Digital Twin events in `az iot dt monitor-events`.

0.8.2
+++++++++++++++
* Resolve jsonschema dependency issue.

0.8.1
+++++++++++++++
* PnP monitor events commands - Adds an option for filtering devices by twin query.
* PnP monitor events commands - Some existing mandatory parameters are now optional.
* Added support for iot central commands, monitor-events and device-twin show.
* Schema validation applies for creation of IoT Edge deployments or when setting modules per device.

0.8.0
+++++++++++++++
* Added Azure IoT Plug & Play public preview functionality.

0.7.1
+++++++++++++++
* Added support for distribution tracing commands.
* Minor fixes.

0.7.0
+++++++++++++++
* Added support for deviceId wildcards and IoT Hub query language filtering to monitor-events.
* Added support for edge offline commands.
* Upgrade service Sdk to 2018-08-30-preview.
* Added --set-parent and --add-children to device-identity create to support edge offline feature.
* BREAKING CHANGES: The commands "az iot hub show-connection-string", "az iot hub device-identity show-connection-string" and "az iot hub module-identity show-connection-string" will no longer return the output with key "cs".

0.6.1
+++++++++++++++
* Added --output support to monitor-events. Supports either json or yaml, i.e. az iot hub monitor-events --hub-name {} -d {} --output yaml
* Changed monitor-events to output JSON by default
* Added support to parse and display payload as JSON if system property Content-Type is provided and application/json (i.e. send-d2c-message ... --props $.ct=application/json from the CLI) or if monitor-events has a property --content-type/--ct of application/json (i.e. monitor-events --ct application/json).

0.6.0
+++++++++++++++
* Upgrade DPS Sdk to V20180901 (#39)
* Add Reprovision and SymmetricKey attestation to the enrollment
* Support allocation-policy in enrollment
* Add new examples in help docs

0.5.4
+++++++++++++++
* Replaced multi-character short options ('-props', for example) with long option prefixes '--' to satisfy Azure CLI CI linter requirements

0.5.3
+++++++++++++++
* uAMQP out of band install will use range rule >=1.0.1,<1.1 instead of exact version
* Reworked monitor-events keyboardinterrupt handling
* Added initial scenario automation document with example script

0.5.2
+++++++++++++++
* Significant reduction in extension install time
* Significant reduction in chance of deadlock on keyboard interrupt when using monitor-events (uamqp dependency incremented to v1.0.1)
* Monitor-events will throw a runtime exception upon errors.
* Catch empty sys.excepthook errors occasionally raised by underlying cancelled futures
* Test improvements + CLI testsdk path change to azure.cli.core.mock.DummyCli

0.5.1
+++++++++++++++
* New command: iot hub monitor-feedback
* Event monitor now supports connection string based usage (via --login)
* Improvements to amqp functionality
* Increment extension target uamqp version to 0.1.1

0.5.0
+++++++++++++++
* New complete command group: hub configuration (supports IoT device configuration)
* New command: edge set-modules (deprecates apply-configuration)
* New commands: <edge deployment or device configuration> show-metric
* Increment to service API version target
* Increment uAMQP to v0.1.0rc1. Dependency install will use exact version (vs compatible)
* Support Homebrew for out of band uAMQP install
* Help Text content++
* Misc tweaks and improvements

0.4.5
+++++++++++++++
* Introduces C2D message send for Python 3.4+.
* Concurrently support 0.4.0 + 0.5.0 IoT mgmt SDK
* Improved top parameter for list ops
* Generalize uamqp dependency check (for operations that require it)

0.4.4
+++++++++++++++
* First release of monitor-events command. Currently supports Python 3.5+, with increased support in future updates.
* Uses uamqp beta5 build as provider and therefore inherits its compatibility.
* Help text improvements.
* Generate sas token duration param will force int.

0.4.3
+++++++++++++++
* Mode 2 login support for most IoT Hub commands. Provide an IoT Hub connection string via --login/-l for commands that support it.
* Added X509 root CA support for DPS enrollment groups
* Reworked device simulator
* Various fixes and tweaks.

0.4.1
+++++++++++++++
* Device Provisioning Service Individual + Group enrollments support secondary cert for identity attestation.
* Encoding issue fixed for listing edge devices (with hub device-identity list -ee)
* IoT Edge workflow improved. Edge device modules will be immediately returned after applying a single device configuration.
* Major internal optimizations in package structure
* Travis CI integration

0.4.0
+++++++++++++++
* Device Provisioning Service functionality added

0.3.2
+++++++++++++++
* Updated command names/path
* First announced release

0.3.0
+++++++++++++++
* Knack based Extension conversion
* Removed C IoT SDK dependencies (Python wrappers of)
* Added numerous IoT data-plane functionality
* Updated extension metadata
* Moved to internal SAS generate method
* Miscellaneous tweaks and improvements

0.2.4
+++++++++++++++
* Build device connection string internally vs iot command module
* Clean-up

0.2.3
+++++++++++++++
* Significant restructing of CLI, prioritizes pure Python solutions where possible
* Provides IoT Edge capabilities
* Adds following new commands:
* iot query
* iot device show
* iot device list
* iot device create
* iot device update
* iot device delete
* iot device twin show
* iot device twin update
* iot device module show
* iot device module list
* iot device module create
* iot device module update
* iot device module delete
* iot device module twin show
* iot device module twin update
* iot device module twin replace
* iot configuration apply
* iot configuration create
* iot configuration update
* iot configuration delete
* iot configuration show
* iot configuration list
* Bug fixes

0.1.2
+++++++++++++++
* Updated extension metadata with tweaked Az CLI names.
* Device simulate supports receive count of infinity and message count of 0.

0.1.1
+++++++++++++++
* Collection of new commands most of which use IoT SDK as the provider
* Show and update device twin
* Invoke device method
* Device simulation
* Hub message send (Cloud-to-device)
* New device message send (Device-to-cloud) supports http, amqp, mqtt
* Get SAS token
