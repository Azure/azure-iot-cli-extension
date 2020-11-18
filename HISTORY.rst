.. :changelog:

Release History
===============

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
