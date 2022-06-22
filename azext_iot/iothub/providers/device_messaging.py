# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os.path import exists, basename
from time import time, sleep
from typing import Dict, Optional
from knack.log import get_logger
from azext_iot.common.shared import DeviceAuthApiType, KeyType, ProtocolType, SdkType, SettleType
from azext_iot.common.utility import (
    handle_service_exception, process_json_arg, read_file_content, validate_key_value_pairs
)
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    CLIInternalError,
    FileOperationError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azext_iot._factory import SdkResolver, CloudError
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.operations.hub import (
    _build_device_or_module_connection_string,
    _iot_device_show,
    _iot_hub_monitor_feedback
)
import pprint


logger = get_logger(__name__)
printer = pprint.PrettyPrinter(indent=2)


class DeviceMessagingProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        device_id: str,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
        login: Optional[str] = None,
        auth_type_dataplane: Optional[str] = None
    ):
        super(DeviceMessagingProvider, self).__init__(
            cmd=cmd, hub_name=hub_name, rg=rg, login=login, auth_type_dataplane=auth_type_dataplane
        )
        self.device_id = device_id
        # prob move this into base - there is one command that needs service + other providers use service sdk
        self.device_resolver = SdkResolver(target=self.target, device_id=device_id)
        self.device_sdk = self.device_resolver.get_sdk(SdkType.device_sdk)

    def device_send_message(
        self,
        data: str = "Ping from Az CLI IoT Extension",
        properties: Optional[str] = None,
        msg_count: int = 1,
        device_symmetric_key: Optional[str] = None,
        certificate_file: Optional[str] = None,
        key_file: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        from azext_iot.iothub.providers.mqtt import MQTTProvider

        device = self._d2c_get_device_auth_props(
            symmetric_key=device_symmetric_key,
            certificate_file=certificate_file,
            key_file=key_file,
            passphrase=passphrase
        )
        if properties:
            properties = validate_key_value_pairs(properties)

        device_connection_string = _build_device_or_module_connection_string(device, KeyType.primary.value)
        client_mqtt = MQTTProvider(
            hub_hostname=self.target["entity"],
            device_conn_string=device_connection_string,
            x509_files=device["authentication"].get("x509_files"),
            device_id=self.device_id
        )
        for _ in range(msg_count):
            client_mqtt.send_d2c_message(message_text=data, properties=properties)
        client_mqtt.shutdown()

    def device_send_message_http(self, data: str, headers: dict = None):
        try:
            return self.device_sdk.device.send_device_event(
                id=self.device_id, message=data, custom_headers=headers
            )
        except CloudError as e:
            handle_service_exception(e)

    def c2d_message_complete(self, etag: str):
        try:
            return self.device_sdk.device.complete_device_bound_notification(
                id=self.device_id, etag=etag
            )
        except CloudError as e:
            handle_service_exception(e)

    def c2d_message_reject(self, etag: str):
        try:
            return self.device_sdk.device.complete_device_bound_notification(
                id=self.device_id, etag=etag, reject=""
            )
        except CloudError as e:
            handle_service_exception(e)

    def c2d_message_abandon(self, etag: str):
        try:
            return self.device_sdk.device.abandon_device_bound_notification(
                id=self.device_id, etag=etag
            )
        except CloudError as e:
            handle_service_exception(e)

    def c2d_message_receive(
        self,
        lock_timeout: int = 60,
        abandon: bool = False,
        complete: bool = False,
        reject: bool = False,
    ):
        ack = None
        ack_vals = [abandon, complete, reject]
        if any(ack_vals):
            if len(list(filter(lambda val: val, ack_vals))) > 1:
                raise MutuallyExclusiveArgumentError(
                    "Only one c2d-message ack argument can be used [--complete, --abandon, --reject]"
                )
            if abandon:
                ack = SettleType.abandon.value
            elif complete:
                ack = SettleType.complete.value
            elif reject:
                ack = SettleType.reject.value

        return self._c2d_message_receive(lock_timeout, ack)

    def _c2d_message_receive(self, lock_timeout: int = 60, ack: Optional[str] = None):
        from azext_iot.constants import MESSAGING_HTTP_C2D_SYSTEM_PROPERTIES

        request_headers = {}
        if lock_timeout:
            request_headers["IotHub-MessageLockTimeout"] = str(lock_timeout)

        try:
            result = self.device_sdk.device.receive_device_bound_notification(
                id=self.device_id, custom_headers=request_headers, raw=True
            ).response

            if result and result.status_code == 200:
                payload = {"properties": {}}

                if "etag" in result.headers:
                    eTag = result.headers["etag"].strip('"')
                    payload["etag"] = eTag

                    if ack:
                        ack_response = {}
                        if ack == SettleType.abandon.value:
                            logger.debug("__Abandoning message__")
                            ack_response = (
                                self.device_sdk.device.abandon_device_bound_notification(
                                    id=self.device_id, etag=eTag, raw=True
                                )
                            )
                        elif ack == SettleType.reject.value:
                            logger.debug("__Rejecting message__")
                            ack_response = (
                                self.device_sdk.device.complete_device_bound_notification(
                                    id=self.device_id, etag=eTag, reject="", raw=True
                                )
                            )
                        else:
                            logger.debug("__Completing message__")
                            ack_response = (
                                self.device_sdk.device.complete_device_bound_notification(
                                    id=self.device_id, etag=eTag, raw=True
                                )
                            )

                        payload["ack"] = (
                            ack
                            if (ack_response and ack_response.response.status_code == 204)
                            else None
                        )

                app_prop_prefix = "iothub-app-"
                app_prop_keys = [
                    header
                    for header in result.headers
                    if header.lower().startswith(app_prop_prefix)
                ]

                app_props = {}
                for key in app_prop_keys:
                    app_props[key[len(app_prop_prefix) :]] = result.headers[key]

                if app_props:
                    payload["properties"]["app"] = app_props

                sys_props = {}
                for key in MESSAGING_HTTP_C2D_SYSTEM_PROPERTIES:
                    if key in result.headers:
                        sys_props[key] = result.headers[key]

                if sys_props:
                    payload["properties"]["system"] = sys_props

                if result.content:
                    target_encoding = result.headers.get("ContentEncoding", "utf-8")
                    logger.info(f"Decoding message data encoded with: {target_encoding}")
                    payload["data"] = result.content.decode(target_encoding)

                return payload
            return
        except CloudError as e:
            handle_service_exception(e)

    def c2d_message_send(
        self,
        data: str = "Ping from Az CLI IoT Extension",
        message_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        content_encoding: str = "utf-8",
        content_type: Optional[str] = None,
        expiry_time_utc: Optional[str] = None,
        properties: Optional[str] = None,
        ack: Optional[str] = None,
        wait_on_feedback: bool = False,
    ):
        if wait_on_feedback and not ack:
            raise RequiredArgumentMissingError(
                'To wait on device feedback, ack must be "full", "negative" or "positive"'
            )

        if properties:
            properties = validate_key_value_pairs(properties)

        if expiry_time_utc:
            now_in_milli = int(time() * 1000)
            user_msg_expiry = int(expiry_time_utc)
            if user_msg_expiry < now_in_milli:
                raise InvalidArgumentValueError("Message expiry time utc is in the past!")

        from azext_iot.monitor import event

        msg_id, errors = event.send_c2d_message(
            target=self.target,
            device_id=self.device_id,
            data=data,
            message_id=message_id,
            correlation_id=correlation_id,
            user_id=user_id,
            content_encoding=content_encoding,
            content_type=content_type,
            expiry_time_utc=expiry_time_utc,
            properties=properties,
            ack=ack,
        )
        if errors:
            raise CLIInternalError(
                "C2D message error: {}, use --debug for more details.".format(errors)
            )

        if wait_on_feedback:
            _iot_hub_monitor_feedback(target=self.target, device_id=self.device_id, wait_on_id=msg_id)

    def c2d_message_purge(self):
        service_sdk = self.get_sdk(SdkType.service_sdk)
        return service_sdk.cloud_to_device_messages.purge_cloud_to_device_message_queue(
            self.device_id
        )

    def simulate_device(
        self,
        receive_settle: str = "complete",
        data: str = "Ping from Az CLI IoT Extension",
        msg_count: int = 100,
        msg_interval: int = 3,
        protocol_type: str = "mqtt",
        properties: Optional[str] = None,
        device_symmetric_key: Optional[str] = None,
        certificate_file: Optional[str] = None,
        key_file: Optional[str] = None,
        passphrase: Optional[str] = None,
        method_response_code: Optional[str] = None,
        method_response_payload: Optional[str] = None,
        init_reported_properties: Optional[str] = None
    ):
        import sys
        import uuid
        import datetime
        import json
        from azext_iot.iothub.providers.mqtt import MQTTProvider
        from threading import Event, Thread
        from tqdm import tqdm
        from azext_iot.constants import (
            MIN_SIM_MSG_INTERVAL,
            MIN_SIM_MSG_COUNT,
            SIM_RECEIVE_SLEEP_SEC,
        )

        protocol_type = protocol_type.lower()
        if protocol_type == ProtocolType.mqtt.name:
            if receive_settle != "complete":
                raise InvalidArgumentValueError('mqtt protocol only supports settle type of "complete"')

        if msg_interval < MIN_SIM_MSG_INTERVAL:
            raise InvalidArgumentValueError("msg interval must be at least {}".format(MIN_SIM_MSG_INTERVAL))

        if msg_count < MIN_SIM_MSG_COUNT:
            raise InvalidArgumentValueError("msg count must be at least {}".format(MIN_SIM_MSG_COUNT))

        if protocol_type != ProtocolType.mqtt.name:
            if method_response_code:
                raise ArgumentUsageError(
                    "'method-response-code' not supported, {} doesn't allow direct methods.".format(protocol_type)
                )
            if method_response_payload:
                raise ArgumentUsageError(
                    "'method-response-payload' not supported, {} doesn't allow direct methods.".format(protocol_type)
                )
            if init_reported_properties:
                raise ArgumentUsageError(
                    "'init-reported-properties' not supported, {} doesn't allow setting twin props".format(protocol_type)
                )
            if certificate_file or key_file:
                raise ArgumentUsageError(
                    "'certificate-file' and 'key-file' not supported, {} doesn't allow x509 "
                    "certificate authentication".format(protocol_type)
                )

        properties_to_send = _simulate_get_default_properties(protocol_type)
        user_properties = validate_key_value_pairs(properties) or {}
        properties_to_send.update(user_properties)

        if method_response_payload:
            method_response_payload = process_json_arg(
                method_response_payload, argument_name="method-response-payload"
            )

        if init_reported_properties:
            init_reported_properties = process_json_arg(
                init_reported_properties, argument_name="init-reported-properties"
            )

        class generator(object):
            def __init__(self):
                self.calls = 0

            def generate(self, jsonify=True):
                self.calls += 1
                payload = {
                    "id": str(uuid.uuid4()),
                    "timestamp": str(datetime.datetime.utcnow()),
                    "data": str(data + " #{}".format(self.calls)),
                }
                return json.dumps(payload) if jsonify else payload

        cancellation_token = Event()

        def http_wrap(generator, msg_interval, msg_count):
            for _ in tqdm(range(0, msg_count), desc='Sending and receiving events via https', ascii=' #'):
                d = generator.generate(False)
                self.device_send_message_http(d, headers=properties_to_send)
                if cancellation_token.wait(msg_interval):
                    break

        try:
            device = self._d2c_get_device_auth_props(
                symmetric_key=device_symmetric_key,
                certificate_file=certificate_file,
                key_file=key_file,
                passphrase=passphrase
            )
            if protocol_type == ProtocolType.mqtt.name:
                device_connection_string = _build_device_or_module_connection_string(device, KeyType.primary.value)

                client_mqtt = MQTTProvider(
                    hub_hostname=self.target["entity"],
                    device_conn_string=device_connection_string,
                    x509_files=device["authentication"].get("x509_files"),
                    device_id=self.device_id,
                    method_response_code=method_response_code,
                    method_response_payload=method_response_payload,
                    init_reported_properties=init_reported_properties
                )
                client_mqtt.execute(
                    data=generator(),
                    properties=properties_to_send,
                    publish_delay=msg_interval,
                    msg_count=msg_count
                )
                client_mqtt.shutdown()
            else:
                op = Thread(
                    target=http_wrap,
                    args=(generator(), msg_interval, msg_count)
                )
                op.start()

                while op.is_alive():
                    self._handle_c2d_msg(receive_settle)
                    sleep(SIM_RECEIVE_SLEEP_SEC)

        except KeyboardInterrupt:
            sys.exit()
        except Exception as x:
            raise CLIInternalError(x)
        finally:
            if cancellation_token:
                cancellation_token.set()

    def device_upload_file(
        self,
        file_path: str,
        content_type: str,
    ):
        from azext_iot.sdk.iothub.device.models import FileUploadCompletionStatus

        if not exists(file_path):
            raise FileOperationError('File path "{}" does not exist!'.format(file_path))

        content = read_file_content(file_path)
        file_name = basename(file_path)

        try:
            upload_meta = self.device_sdk.device.create_file_upload_sas_uri(
                device_id=self.device_id, blob_name=file_name, raw=True
            ).response.json()
            storage_endpoint = "{}/{}/{}{}".format(
                upload_meta["hostName"],
                upload_meta["containerName"],
                upload_meta["blobName"],
                upload_meta["sasToken"],
            )
            completion_status = FileUploadCompletionStatus(
                correlation_id=upload_meta["correlationId"], is_success=True
            )
            upload_response = self.device_sdk.device.upload_file_to_container(
                storage_endpoint=storage_endpoint,
                content=content,
                content_type=content_type,
            )
            completion_status.status_code = upload_response.status_code
            completion_status.status_reason = upload_response.reason

            return self.device_sdk.device.update_file_upload_status(
                device_id=self.device_id, file_upload_completion_status=completion_status
            )
        except CloudError as e:
            handle_service_exception(e)

    def _d2c_get_device_auth_props(
        self,
        symmetric_key: Optional[str] = None,
        certificate_file: Optional[str] = None,
        key_file: Optional[str] = None,
        passphrase: Optional[str] = None
    ):
        if symmetric_key:
            return {
                "hub": self.target["entity"],
                "deviceId": self.device_id,
                "authentication": {
                    "type": DeviceAuthApiType.sas.value,
                    "symmetricKey": {
                        "primaryKey": symmetric_key
                    }
                }
            }
        elif (certificate_file and key_file):
            # custom device structure to hold needed info
            # Note that here signed vs ca doesnt matter. CA will need a verified cert in the service
            # Note that for the CA device the subject of the cert must be the device_id
            return {
                "deviceId": self.device_id,
                "authentication": {
                    "type": DeviceAuthApiType.selfSigned.value,
                    "x509_files": {
                        "certificateFile": certificate_file,
                        "keyFile": key_file,
                        "passphrase": passphrase
                    }
                }
            }
        elif any([certificate_file, key_file, passphrase]):
            raise RequiredArgumentMissingError(
                "Both 'certificate-file' and 'key-file' required for x509 certificate authentication."
            )
        else:
            # Get the device info from the service side
            return _iot_device_show(self.target, self.device_id)

    def _handle_c2d_msg(self, receive_settle: str, lock_timeout: int = 60):
        result = self._c2d_message_receive(lock_timeout)
        if result:
            print()
            print("C2D Message Handler [Received C2D message]:")
            printer.pprint(result)
            if receive_settle == "reject":
                print("C2D Message Handler [Rejecting message]")
                self.c2d_message_reject(result["etag"])
            elif receive_settle == "abandon":
                print("C2D Message Handler [Abandoning message]")
                self.c2d_message_abandon(result["etag"])
            else:
                print("C2D Message Handler [Completing message]")
                self.c2d_message_complete(result["etag"])
            return True
        return False


def _simulate_get_default_properties(protocol: str) -> Dict[str, str]:
    default_properties = {}
    is_mqtt = protocol == ProtocolType.mqtt.name

    default_properties["$.ct" if is_mqtt else "content-type"] = "application/json"
    default_properties["$.ce" if is_mqtt else "content-encoding"] = "utf-8"

    return default_properties
