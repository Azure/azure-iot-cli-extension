.. :changelog:

Release History
===============

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
