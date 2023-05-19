# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for IoT Hub commands.
"""

from knack.help_files import helps


def load_iothub_help():

    helps["iot hub job"] = """
        type: group
        short-summary: Manage IoT Hub jobs (v2).
    """

    helps["iot hub job create"] = """
        type: command
        short-summary: Create and schedule an IoT Hub job for execution.
        long-summary: |
                      When scheduling a twin update job, the twin patch is a required argument.
                      When scheduling a device method job, the method name and payload are required arguments.
                      PLEASE NOTE: Using a custom start time that's in the past may cause the operation to fail.

        examples:
        - name: Create and schedule a job to update the twin tags of all devices.
          text: >
            az iot hub job create --job-id {job_id} --job-type scheduleUpdateTwin -n {iothub_name} -q "*" --twin-patch '{"tags": {"deviceType": "Type1, Type2, Type3"}}'

        - name: Schedule job and block for result of "completed", "failed" or "cancelled". Specify poll interval in seconds.
          text: >
            az iot hub job create --job-id {job_id} --job-type scheduleUpdateTwin -n {iothub_name} -q "*" --twin-patch '{"tags": {"deviceType": "Type1, Type2, Type3"}}'
            --wait --poll-interval 30

        - name: Create a job to update a desired twin property on a subset of devices, scheduled to run at an arbitrary future time.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleUpdateTwin -n {iothub_name} --twin-patch '{"properties":{"desired": {"temperatureF": 65}}}'
            --start-time "2050-01-08T12:19:56.868Z" --query-condition "deviceId IN ['MyDevice1', 'MyDevice2', 'MyDevice3']"

        - name: Create and schedule a job to invoke a device method for a set of devices meeting a query condition.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleDeviceMethod -n {iothub_name} --method-name setSyncIntervalSec --method-payload 30
            --query-condition "properties.reported.settings.syncIntervalSec != 30"

        - name:  Create and schedule a job to invoke a device method for all devices.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleDeviceMethod -q "*" -n {iothub_name}
            --method-name setSyncIntervalSec --method-payload '{"version":"1.0"}'
    """

    helps["iot hub job show"] = """
        type: command
        short-summary: Show details of an existing IoT Hub job.

        examples:
        - name: Show the details of a created job.
          text: >
            az iot hub job show --hub-name {iothub_name} --job-id {job_id}
    """

    helps["iot hub job list"] = """
        type: command
        short-summary: List the historical jobs of an IoT Hub.

        examples:
        - name: List all archived jobs within retention period (max of 30 days).
          text: >
            az iot hub job list --hub-name {iothub_name}
        - name: List all archived jobs projecting specific properties
          text: >
            az iot hub job list --hub-name {iothub_name} --query "[*].[jobId,type,status,startTime,endTime]"
        - name: List only update twin type jobs
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type scheduleDeviceMethod
        - name: List device method jobs which have status "scheduled"
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type scheduleDeviceMethod --job-status scheduled
        - name: List device export jobs which have status "completed"
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type export --job-status completed
    """

    helps["iot hub job cancel"] = """
        type: command
        short-summary: Cancel an IoT Hub job.

        examples:
        - name: Cancel an IoT Hub job.
          text: >
            az iot hub job cancel --hub-name {iothub_name} --job-id {job_id}
    """

    helps["iot hub digital-twin"] = """
        type: group
        short-summary: Manipulate and interact with the digital twin of an IoT Hub device.
    """

    helps["iot hub digital-twin invoke-command"] = """
        type: command
        short-summary: Invoke a root or component level command of a digital twin device.

        examples:
        - name: In general, invoke command which takes a payload that includes certain property using inline JSON.
          text: >
            az iot hub digital-twin invoke-command --command-name {command_name} -n {iothub_name} -d {device_id} --payload '{"property_name": "property_value"}'

        - name: |
                Invoke root level command "reboot" which takes a payload named "delay" conforming to DTDL model
                https://github.com/Azure/opendigitaltwins-dtdl/blob/master/DTDL/v2/samples/TemperatureController.json.
          text: >
            az iot hub digital-twin invoke-command --command-name reboot -n {iothub_name} -d {device_id} --payload 5

        - name: Invoke command "getMaxMinReport" on component "thermostat1" that takes no input.
          text: >
            az iot hub digital-twin invoke-command --cn getMaxMinReport -n {iothub_name} -d {device_id} --component-path thermostat1
    """

    helps["iot hub digital-twin show"] = """
        type: command
        short-summary: Show the digital twin of an IoT Hub device.

        examples:
        - name: Show the target device digital twin.
          text: >
            az iot hub digital-twin show -n {iothub_name} -d {device_id}
    """

    helps["iot hub digital-twin update"] = """
        type: command
        short-summary: Update the read-write properties of a digital twin device via JSON patch specification.
        long-summary: Currently operations are limited to add, replace and remove.

        examples:
        - name: Update a digital twin via JSON patch specification.
          text: >
            az iot hub digital-twin update --hub-name {iothub_name} --device-id {device_id}
            --json-patch '{"op":"add", "path":"/thermostat1/targetTemperature", "value": 54}'

        - name: Update a digital twin via JSON patch specification.
          text: >
            az iot hub digital-twin update -n {iothub_name} -d {device_id}
            --json-patch '[
              {"op":"remove", "path":"/thermostat1/targetTemperature"},
              {"op":"add", "path":"/thermostat2/targetTemperature", "value": 22}
            ]'

        - name: Update a digital twin property via JSON patch specification defined in a file.
          text: >
            az iot hub digital-twin update -n {iothub_name} -d {device_id}
            --json-patch ./my/patch/document.json
    """

    helps[
        "iot device"
    ] = """
        type: group
        short-summary: Leverage device simulation and other device-centric operations such as device-to-cloud or
          cloud-to-device messaging capabilities.
    """

    helps[
        "iot device c2d-message"
    ] = """
        type: group
        short-summary: Cloud-to-device messaging commands.
    """

    helps[
        "iot device c2d-message abandon"
    ] = """
        type: command
        short-summary: Abandon a cloud-to-device message.
    """

    helps[
        "iot device c2d-message complete"
    ] = """
        type: command
        short-summary: Complete a cloud-to-device message.
    """

    helps[
        "iot device c2d-message receive"
    ] = """
        type: command
        short-summary: Receive a cloud-to-device message.
        long-summary: |
                      The received message body will only be decoded when its content-encoding
                      is set to 'utf-8', 'utf-16' or 'utf-32'. The message payload will be
                      displayed as {{non-decodable payload}} when content-encoding is not
                      set to one of the above, or fails to decode even when content-encoding
                      is set to one of the above.

                      Note: Only one message ack argument [--complete, --reject, --abandon] will be accepted.
        examples:
        - name: Basic usage
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group}
        - name: Receive a message and set a lock timeout of 30 seconds for that message
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --lt {30}
        - name: Receive a message and ack it as 'complete' after it is received
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --complete
        - name: Receive a message and reject it after it is received
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --reject
    """

    helps[
        "iot device c2d-message reject"
    ] = """
        type: command
        short-summary: Reject or deadletter a cloud-to-device message.
    """

    helps[
        "iot device c2d-message purge"
    ] = """
        type: command
        short-summary: Purge cloud-to-device message queue for a target device.
    """

    helps[
        "iot device c2d-message send"
    ] = """
        type: command
        short-summary: Send a cloud-to-device message.
        long-summary: |
                      This command relies on and may install dependent Cython package (uamqp) upon first execution.
                      https://github.com/Azure/azure-uamqp-python

                      Note: Content-encoding is defaulted to utf-8. The command will send the message body
                      with encoding action when the content-encoding property is either utf-8, utf-16 or
                      utf-32. If the content-encoding value is not one of these, the property will still
                      be sent with no encoding action taken.

                      When sending a binary message body, the content must be provided from a file
                      (via `--data-file-path`) and content-type must be set to `application/octet-stream`.
        examples:
        - name: Basic usage with default message body
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name}
        - name: Send cloud-to-device message with custom data and properties.
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --data 'Hello World' --props 'key0=value0;key1=value1'
        - name: Send a C2D message and wait for device acknowledgement
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --ack full --wait
        - name: Send a C2D message in binary format from a file.
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --data-file-path {file_path} --content-type 'application/octet-stream'
        - name: Send a C2D message in JSON format from a file.
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --data-file-path {file_path} --content-type 'application/json'
    """

    helps[
        "iot device send-d2c-message"
    ] = """
        type: command
        short-summary: Send an mqtt device-to-cloud message.
        long-summary: |
                      The command supports sending messages with custom payload in unicode
                      string or binary format. When intending to send binary, the data should
                      come from a file (via `--data-file-path`) and content type should be set
                      to `application/octet-stream`.

                      Note: The command only works for symmetric key auth (SAS) based devices.
                      To enable querying on a message body in message routing, the contentType
                      system property must be application/JSON and the contentEncoding system
                      property must be one of the UTF encoding values supported by that system
                      property(UTF-8, UTF-16 or UTF-32). If the content encoding isn't set when
                      Azure Storage is used as routing endpoint, then IoT Hub writes the messages
                      in base 64 encoded format. If using x509 authentication methods, the
                      certificate and key files (and passphrase if needed) must be provided.
        examples:
        - name: Basic usage
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id}
        - name: Basic usage for device registering the model Id of 'dtmi:com:example:Thermostat;1' upon connection
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --model-id 'dtmi:com:example:Thermostat;1'
        - name: Basic usage for device with x509 authentication
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path}
        - name: Basic usage for device with x509 authentication in which the key file has a passphrase
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path} --pass {passphrase}
        - name: Basic usage with custom data
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --data {message_body}
        - name: Send application properties
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props 'key0=value0;key1=value1'
        - name: Send system properties (Message Id and Correlation Id)
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props '$.mid=<id>;$.cid=<id>'
        - name: Send custom data by specifying content-type and content-encoding in system properties
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props '$.ct=<content-type>;$.ce=<content-encoding>' --data {message_body}
        - name: Send custom data in binary format by specifying content-encoding in system properties
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props '$.ct=application/octet-stream' --data-file-path {file_path}
        - name: Send custom data in JSON format by specifying content-type and content-encoding in system properties
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props '$.ct=application/json;$.ce=utf-8' --data-file-path {file_path}
    """

    helps[
        "iot device simulate"
    ] = """
        type: command
        short-summary: Simulate a device in an Azure IoT Hub.
        long-summary: |
                      While the device simulation is running, the device will automatically receive
                      and acknowledge cloud-to-device (c2d) messages. For mqtt simulation, all c2d messages will
                      be acknowledged with completion. For http simulation c2d acknowledgement is based on user
                      selection which can be complete, reject or abandon. The mqtt simulation also supports direct
                      method invocation which can be acknowledged by a response status code and response payload.
                      Note: The command by default will set content-type to application/json and content-encoding
                      to utf-8. This can be overriden.
                      Note: If using x509 authentication methods, the certificate and key files (and passphrase if needed) must be provided.
        examples:
        - name: Basic usage (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id}
        - name: Basic usage for device registering the model Id of 'dtmi:com:example:Thermostat;1' upon connection (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --model-id 'dtmi:com:example:Thermostat;1'
        - name: Basic usage for device with x509 authentication (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path}
        - name: Basic usage for device with x509 authentication (mqtt) in which the key file has a passphrase
          text: az iot device simulate -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path} --pass {passphrase}
        - name: Send mixed properties (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --properties "myprop=myvalue;$.ct=application/json"
        - name: Send direct method response status code and direct method response payload as raw json (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --method-response-code 201 --method-response-payload '{"result":"Direct method successful"}'
        - name: Send direct method response status code and direct method response payload as path to local file (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --method-response-code 201 --method-response-payload '../my_direct_method_payload.json'
        - name: Send the initial state of device twin reported properties as raw json for the target device (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --init-reported-properties '{"reported_prop_1":"val_1", "reported_prop_2":val_2}'
        - name: Send the initial state of device twin reported properties as path to local file for the target device (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --init-reported-properties '../my_device_twin_reported_properties.json'
        - name: Basic usage (http)
          text: az iot device simulate -n {iothub_name} -d {device_id} --protocol http
        - name: Send mixed properties (http)
          text: az iot device simulate -n {iothub_name} -d {device_id} --protocol http --properties
                "iothub-app-myprop=myvalue;content-type=application/json;iothub-correlationid=12345"
        - name: Choose total message count and interval between messages
          text: az iot device simulate -n {iothub_name} -d {device_id} --msg-count 1000 --msg-interval 5
        - name: Reject c2d messages (http only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --rs reject --protocol http
        - name: Abandon c2d messages (http only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --rs abandon --protocol http
    """

    helps[
        "iot device upload-file"
    ] = """
        type: command
        short-summary: Upload a local file as a device to a pre-configured blob storage container.
    """

    helps["iot edge devices"] = """
        type: group
        short-summary: Commands to manage IoT Edge devices.
    """

    helps["iot edge devices create"] = """
        type: command
        short-summary: Create and configure multiple edge devices in an IoT Hub.
        long-summary: |
          This operation accepts inline device arguments or an edge devices configuration file in YAML or JSON format.
          Inline command args (like '--device-auth') will take precedence and override configuration file properties if they are provided.
          A sample configuration file can be found here: https://aka.ms/aziotcli-edge-devices-config
          Review examples and parameter descriptions for details on how to fully utilize this operation.

        examples:
        - name: Create a couple of edge devices using symmetric key auth (default)
          text: |
            az iot edge devices create -n {hub_name} --device id=device_1 --device id=device_2

        - name: Create a flat list of edge devices using self-signed certificate authentication with various edge property configurations, using inline arguments.
          text: |
            az iot edge devices create -n {hub_name} --device-auth x509_thumbprint --default-edge-agent "mcr.microsoft.com/azureiotedge-agent:1.4"
            --device id=device_1 hostname={FQDN}
            --device id=device_2 edge_agent={agent_image}
            --device id=parent hostname={FQDN} edge_agent={agent_image} container_auth={path_or_json_string}

        - name: Delete all existing device-identities on a hub and create new devices based on a configuration file (with progress bars and visualization output).
          text: >
            az iot edge devices create -n {hub_name} --cfg path/to/config_yml_or_json -c -v

        - name: Create a group of nested edge devices with custom module deployments - containing 2 parent devices with 1 child device each, using inline arguments.
            Also specifies output path for device certificate bundles.
          text: |
            az iot edge devices create -n {hub_name} --out {device_bundle_path}
            --device id=parent_1 deployment=/path/to/parentDeployment_1.json
            --device id=child_1 parent=parent_1 deployment=/path/to/child_deployment_1.json
            --device id=parent_2 deployment=/path/to/parentDeployment_2.json
            --device id=child_2 parent=parent_2 deployment=/path/to/child_deployment_2.json

        - name: Create a simple nested edge device configuration with an existing root CA, using x509 auth, and specify a custom device bundle output path.
          text: |
            az iot edge devices create -n {hub_name} --out {device_bundle_path}
            --root-cert "root_cert.pem" --root-key "root_key.pem" --device-auth x509_thumbprint
            --device id=parent1
            --device id=child1 parent=parent1
    """

    helps[
        "iot hub state"
    ] = """
        type: group
        short-summary: Manage the state of an IoT Hub.
        long-summary: For more information, see aka.ms/aziotcli-iot-hub-state
    """

    helps[
        "iot hub state export"
    ] = """
        type: command
        short-summary: Export the state of an IoT Hub to a file.
        long-summary: |
                       By default, the exported state will include: arm template for hub, hub configurations (including ADM
                       configurations and edge deployments), device information (including device identites,
                       device twins, module identities and module twins).

                       For more information, see aka.ms/aziotcli-iot-hub-state
        examples:
        - name: Export the supported state of the specified hub to the specified file.
          text: >
            az iot hub state export -n {iothub_name} -f {state_filename}
        - name: Export the supported state of the specified hub to the specified file, overwriting the file contents.
          text: >
            az iot hub state export -n {iothub_name} -f {state_filename} -r
        - name: Export only the devices and configurations of the specified hub to the specified file.
          text: >
            az iot hub state export -n {iothub_name} -f {state_filename} --aspects devices configurations
    """

    helps[
        "iot hub state import"
    ] = """
        type: command
        short-summary: Import a Hub state from a file to an IoT Hub.
        long-summary: |
                       If the arm aspect is specified, the hub will be created if it does not exist.

                       By default, the imported state will include: arm template for hub, hub configurations (including ADM
                       configurations and edge deployments), device information (including device identites,
                       device twins, module identities and module twins).

                       For imported endpoints with system assigned identity authentication, the specified hub must have
                       the correct permissions. Otherwise the command will fail.

                       Private endpoints will be ignored in the import process.

                       For more information, see aka.ms/aziotcli-iot-hub-state
        examples:
        - name: Import the supported state from the specified file to the specified hub.
          text: >
            az iot hub state import -n {iothub_name} -f {state_filename}
        - name: Import the supported state from the specified file to the specified hub, overwriting the previous state of the hub. All
                certificates, configurations, and devices will be deleted before the new state is uploaded.
          text: >
            az iot hub state import -n {iothub_name} -f {state_filename} -r
        - name: Import only the arm template from the specified file to the specified hub. Note that this will create a new hub if
                it does not exist. The file may contain the devices and configurations but those will be ignored.
          text: >
            az iot hub state import -n {iothub_name} -g {resource_group} -f {state_filename} --aspects arm
        - name: Import only the devices and configurations from the specified file to the specified hub. Note that this will NOT
                create a new hub if it does not exist and the command will fail. The file may contain the arm template but that
                will be ignored.
          text: >
            az iot hub state import -n {iothub_name} -f {state_filename} --aspects devices configurations
    """

    helps[
        "iot hub state migrate"
    ] = """
        type: command
        short-summary: Migrate the state of one hub to another hub without saving to a file.
        long-summary: |
                       If the arm aspect is specified, the hub will be created if it does not exist.

                       By default, the migrated state will include: arm template for hub, hub configurations (including ADM
                       configurations and edge deployments), device information (including device identites,
                       device twins, module identities and module twins).

                       For migrated endpoints with system assigned identity authentication, the specified hub must have
                       the correct permissions. Otherwise the command will fail.

                       Private endpoints will be ignored in the migration process.

                       If you have trouble migrating, please use the export and import commands to have a file as a backup.

                       For more information, see aka.ms/aziotcli-iot-hub-state
        examples:
        - name: Migrate the supported state of the origin hub to the destination hub.
          text: >
            az iot hub state migrate --destination-hub {dest_hub_name} --origin-hub {orig_hub_name}
        - name: Migrate the supported state of the origin hub to the destination hub, overwriting the previous state of the hub. All
                certificates, configurations, and devices in the destination hub will be deleted before the new state is uploaded.
          text: >
            az iot hub state migrate --destination-hub {dest_hub_name} --origin-hub {orig_hub_name} -r
        - name: Migrate only the arm template from the origin hub to the destination hub. Note that this will create a new hub if
                the destination hub does not exist. The origin hub may contain the devices and configurations but those will be ignored.
          text: >
            az iot hub state migrate --destination-hub {dest_hub_name} --destination-resource-group {dest_hub_resource_group} --origin-hub {orig_hub_name} --aspects arm
        - name: Migrate only the devices and configurations from the origin hub to the destination hub. Note that this will NOT
                create a new hub if the destination hub does not exist and the command will fail. The arm template for the origin hub
                will be ignored.
          text: >
            az iot hub state migrate --destination-hub {dest_hub_name} --origin-hub {orig_hub_name} --aspects devices configurations
    """

    helps[
        "iot hub message-endpoint"
    ] = """
        type: group
        short-summary: Manage custom endpoints of an IoT hub.
    """

    helps[
        "iot hub message-endpoint create"
    ] = """
        type: group
        short-summary: Add an endpoint to an IoT Hub.
    """

    helps[
        "iot hub message-endpoint create cosmosdb-container"
    ] = """
        type: command
        short-summary: Add a Cosmos DB Container endpoint for an IoT Hub.
        examples:
          - name: Create a key-based Cosmos DB Container endpoint for an IoT Hub.
            text: >
              az iot hub message-endpoint create cosmosdb-container -n {iothub_name} --en {endpoint_name} --container {container}
              --db {database} --endpoint-account {account_name}
          - name: Create a Cosmos DB Container endpoint for an IoT Hub using a connection string.
            text: >
                az iot hub message-endpoint create cosmosdb-container -n {iothub_name} --en {endpoint_name} -c {connection_string}
                --container {container} --db {database}
          - name: Create a Cosmos DB Container endpoint for an IoT Hub using the specified primary key and endpoint uri.
            text: >
              az iot hub message-endpoint create cosmosdb-container -n {iothub_name} --en {endpoint_name} --pk {primary_key}
              --endpoint-uri {endpoint_uri} --container {container} --db {database}
          - name: Create a Cosmos DB Container endpoint for an IoT Hub using system assigned identity and a partition key name.
                  The partition key template will be the default.
            text: >
              az iot hub message-endpoint create cosmosdb-container -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --container {container} --db {database} --pkn {partition_key_name} --identity [system]
          - name: Create a Cosmos DB Container endpoint for an IoT Hub using user assigned identity, partition key name, and partition key template.
            text: >
              az iot hub message-endpoint create cosmosdb-container -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --container {container} --db {database} --pkn {partition_key_name} --pkt {partition_key_template}
              --identity {user_identity_resource_id}
    """

    helps[
        "iot hub message-endpoint create eventhub"
    ] = """
        type: command
        short-summary: Add an Event Hub endpoint for an IoT Hub.
        examples:
          - name: Create a key-based Event Hub endpoint for an IoT Hub.
            text: >
              az iot hub message-endpoint create eventhub -n {iothub_name} --en {endpoint_name} --namespace {namespace_name}
              --entity-path {entity_path} --policy {policy_name}
          - name: Create an Event Hub endpoint for an IoT Hub using a connection string. The endpoint uri and entity path are omitted.
            text: >
              az iot hub message-endpoint create eventhub -n {iothub_name} --en {endpoint_name} -c {connection_string}
          - name: Create an Event Hub endpoint for an IoT Hub using system assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create eventhub -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity [system]
          - name: Create an Event Hub endpoint for an IoT Hub using user assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create eventhub -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity {user_identity_resource_id}
    """

    helps[
        "iot hub message-endpoint create servicebus-queue"
    ] = """
        type: command
        short-summary: Add a Service Bus Queue endpoint for an IoT Hub.
        examples:
          - name: Create a key-based Service Bus Queue endpoint for an IoT Hub.
            text: >
              az iot hub message-endpoint create servicebus-queue -n {iothub_name} --en {endpoint_name} --namespace {namespace_name}
              --entity-path {entity_path} --policy {policy_name}
          - name: Create a Service Bus Queue endpoint for an IoT Hub using a connection string. The endpoint uri and entity path are omitted.
            text: >
              az iot hub message-endpoint create servicebus-queue -n {iothub_name} --en {endpoint_name} -c {connection_string}
          - name: Create a Service Bus Queue endpoint for an IoT Hub using system assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create servicebus-queue -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity [system]
          - name: Create a Service Bus Queue endpoint for an IoT Hub using user assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create servicebus-queue -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity {user_identity_resource_id}
    """

    helps[
        "iot hub message-endpoint create servicebus-topic"
    ] = """
        type: command
        short-summary: Add a Service Bus Topic endpoint for an IoT Hub.
        examples:
          - name: Create a key-based Service Bus Topic endpoint for an IoT Hub.
            text: >
              az iot hub message-endpoint create servicebus-topic -n {iothub_name} --en {endpoint_name} --namespace {namespace_name}
              --entity-path {entity_path} --policy {policy_name}
          - name: Create a Service Bus Topic endpoint for an IoT Hub using a connection string. The endpoint uri and entity path are omitted.
            text: >
              az iot hub message-endpoint create servicebus-topic -n {iothub_name} --en {endpoint_name} -c {connection_string}
          - name: Create a Service Bus Topic endpoint for an IoT Hub using system assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create servicebus-topic -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity [system]
          - name: Create a Service Bus Topic endpoint for an IoT Hub using user assigned identity. The endpoint and entity path must be specified.
            text: >
              az iot hub message-endpoint create servicebus-topic -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --entity-path {entity_path} --identity {user_identity_resource_id}
    """

    helps[
        "iot hub message-endpoint create storage-container"
    ] = """
        type: command
        short-summary: Add a Storage Container endpoint for an IoT Hub.
        examples:
          - name: Create a key-based Storage Container endpoint for an IoT Hub.
            text: >
              az iot hub message-endpoint create storage-container -n {iothub_name} --en {endpoint_name} --container {container_name}
              --endpoint-account {account_name}
          - name: Create a Storage Container endpoint for an IoT Hub using a connection string. The endpoint uri is omitted.
            text: >
              az iot hub message-endpoint create storage-container -n {iothub_name} --en {endpoint_name} -c {connection_string}
              --container {container_name}
          - name: Create a Storage Container endpoint for an IoT Hub using system assigned identity with the given batch frequency, chunk size,
                  and file name format. The endpoint must be specified.
            text: >
              az iot hub message-endpoint create storage-container -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --container {container_name} -b {batch_frequency} -w {chunk_size} --ff {file_format} --identity [system]
          - name: Create a Storage Container endpoint for an IoT Hub using user assigned identity with json encoding. The endpoint must be specified.
            text: >
              az iot hub message-endpoint create storage-container -n {iothub_name} --en {endpoint_name} --endpoint-uri {endpoint_uri}
              --container {container_name} --encoding json --identity {user_identity_resource_id}
    """

    helps[
        "iot hub message-endpoint list"
    ] = """
        type: command
        short-summary: Get information on all the endpoints for an IoT Hub.
        long-summary: You can also specify which endpoint type you want to get information on.
        examples:
          - name: Get all the endpoints from an IoT Hub.
            text: >
              az iot hub message-endpoint list -n {iothub_name}
          - name: Get all the endpoints of type "EventHub" from an IoT Hub.
            text: >
              az iot hub message-endpoint list -n {iothub_name} --endpoint-type eventhub
    """

    helps[
        "iot hub message-endpoint show"
    ] = """
        type: command
        short-summary: Get information on mentioned endpoint for an IoT Hub.
        examples:
          - name: Get an endpoint information from an IoT Hub.
            text: |
              az iot hub message-endpoint show -n {iothub_name} --endpoint-name {endpoint_name}
    """

    helps[
        "iot hub message-endpoint delete"
    ] = """
        type: command
        short-summary: Delete all or a specific endpoint for an IoT Hub.
        long-summary:  You must delete any routes and message enrichments to the endpoint, before deleting the endpoint.
        examples:
          - name: Delete an endpoint from an IoT Hub.
            text: >
              az iot hub message-endpoint delete -n {iothub_name} --endpoint-name {endpoint_name}
          - name: Delete all the endpoints of type "EventHub" from an IoT Hub.
            text: >
              az iot hub message-endpoint delete -n {iothub_name} --endpoint-type eventhub
          - name: Delete all the endpoints from an IoT Hub.
            text: >
              az iot hub message-endpoint delete -n {iothub_name}
          - name: Force delete an endpoint from an IoT Hub. This will delete any routes and message enrichments
                  associated with this endpoint.
            text: >
              az iot hub message-endpoint delete -n {iothub_name} --endpoint-name {endpoint_name} -f
          - name: Force delete  all the endpoints of type "EventHub" from an IoT Hub. This will delete any routes and
                  message enrichments associated with this endpoint.
            text: >
              az iot hub message-endpoint delete -n {iothub_name} --endpoint-type eventhub -f
    """

    helps[
        "iot hub message-route"
    ] = """
        type: group
        short-summary: Manage routes of an IoT hub.
    """

    helps[
        "iot hub message-route create"
    ] = """
        type: command
        short-summary: Add a route for an IoT Hub.
        examples:
          - name: Create a route for an IoT Hub with the given endpoint and source type "DeviceMessages".
            text: >
              az iot hub message-route create -n {iothub_name} --route-name {route_name} --endpoint-name {endpoint_name} --source DeviceMessages
          - name: Create a route for an IoT Hub with the built-in endpoint and source type "DeviceMessages".
            text: >
              az iot hub message-route create -n {iothub_name} --route-name {route_name} --endpoint-name events --source DeviceMessages
          - name: Create a disabled route for an IoT Hub with the given endpoint, source type "DigitalTwinChangeEvents" and custom condition.
            text: >
              az iot hub message-route create -n {iothub_name} --route-name {route_name} --endpoint-name {endpoint_name} --source DigitalTwinChangeEvents
              --condition {condition} --enabled false
    """

    helps[
        "iot hub message-route update"
    ] = """
        type: command
        short-summary: Update a route for an IoT Hub.
        long-summary: You can change the source, endpoint, condition, or enabled state on the route.
        examples:
          - name: Update a route to a given endpoint and source type "DeviceMessages".
            text: >
              az iot hub message-route update -n {iothub_name} --route-name {route_name} --endpoint-name {endpoint_name} --source DeviceMessages
          - name: Disable a route.
            text: >
              az iot hub message-route update -n {iothub_name} --route-name {route_name} --enabled false
          - name: Change a route's condition.
            text: >
              az iot hub message-route update -n {iothub_name} --route-name {route_name} --condition {condition}
    """

    helps[
        "iot hub message-route show"
    ] = """
        type: command
        short-summary: Get information about the route in an IoT Hub.
        examples:
          - name: Get route information from an IoT Hub.
            text: >
              az iot hub message-route show -n {iothub_name} --route-name {route_name}
    """

    helps[
        "iot hub message-route list"
    ] = """
        type: command
        short-summary: Get all the routes in an IoT Hub.
        examples:
          - name: Get all routes from an IoT Hub.
            text: >
              az iot hub message-route list -n {iothub_name}
          - name: Get all the routes of source type "DeviceMessages" from an IoT Hub.
            text: >
              az iot hub message-route list -n {iothub_name} --source DeviceMessages
    """

    helps[
        "iot hub message-route delete"
    ] = """
        type: command
        short-summary: Delete all routes or a mentioned route in an IoT Hub.
        examples:
          - name: Delete a route from an IoT Hub.
            text: >
              az iot hub message-route delete -n {iothub_name} --route-name {route_name}
          - name: Delete all routes of source type "DeviceMessages" from an IoT Hub.
            text: >
              az iot hub message-route delete -n {iothub_name} --source DeviceMessages
          - name: Delete all routes from an IoT Hub.
            text: >
              az iot hub message-route delete -n {iothub_name}
    """

    helps[
        "iot hub message-route test"
    ] = """
        type: command
        short-summary: Test all routes or a mentioned route in an IoT Hub.
        long-summary: You can provide a sample message to test your routes.
        examples:
          - name: Test a route from an IoT Hub.
            text: >
              az iot hub message-route test -n {iothub_name} --route-name {route_name}
          - name: Test all routes of source type "DeviceMessages" from an IoT Hub.
            text: >
              az iot hub message-route test -n {iothub_name} --source DeviceMessages
          - name: Test all route from an IoT Hub with a custom message, including body, app properties, and system properties.
            text: >
              az iot hub message-route test -n {iothub_name} -b {body} --ap {app_properties} --sp {system_properties}
    """

    helps[
        "iot hub message-route fallback"
    ] = """
        type: group
        short-summary: Manage the fallback route of an IoT hub.
    """

    helps[
        "iot hub message-route fallback show"
    ] = """
        type: command
        short-summary: Show the fallback route of an IoT Hub
        examples:
          - name: Show the fallback route from an IoT Hub.
            text: >
              az iot hub message-route fallback show -n {iothub_name}
    """

    helps[
        "iot hub message-route fallback set"
    ] = """
        type: command
        short-summary: Enable or disable the fallback route in an IoT Hub.
        examples:
          - name: Enable the fallback route in an IoT Hub
            text: >
              az iot hub message-route fallback set -n {iothub_name} --enabled true
          - name: Disable the fallback route in an IoT Hub.
            text: >
              az iot hub message-route fallback set -n {iothub_name} --enabled false
    """

    helps["iot hub certificate root-authority"] = """
        type: group
        short-summary: Manage the certificate root-authority for an IoT Hub instance.
    """

    helps["iot hub certificate root-authority set"] = """
        type: command
        short-summary: Set the certificate root-authority for an IoT Hub instance to a specific version.
        long-summary: Transition this resource to a certificate on the DigiCert Global G2 root (v2) or revert to Baltimore root (v1).
          Before making this transition, please ensure all devices are updated to contain the public portion of the root
          that the IoT Hub will be transitioned to. Devices will disconnect and reconnect using the new root.
          We suggest monitoring current connections but an user defined metric may be more appropriate for your situation.
        examples:
        - name: Transition the target IoT Hub certificate root authority to Digicert.
          text: >
            az iot hub certificate root-authority set --hub-name {iothub_name} --certificate-authority v2
        - name: Revert the target IoT Hub certificate root authority to Baltimore.
          text: >
            az iot hub certificate root-authority set --hub-name {iothub_name} --certificate-authority v1
    """

    helps["iot hub certificate root-authority show"] = """
        type: command
        short-summary: Show the current certificate root-authority for an IoT Hub instance.
        examples:
        - name: Show the target IoT Hub certificate root authority.
          text: >
            az iot hub certificate root-authority show --hub-name {iothub_name}
    """
