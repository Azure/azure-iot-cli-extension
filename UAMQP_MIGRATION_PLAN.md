# Pure Python AMQP Implementation Design

## Overview

The Azure IoT CLI extension uses pure Python AMQP implementations instead of the C-based `uamqp` library:
- **`azure-eventhub`** (`EventHubConsumerClient`) for device telemetry monitoring
- **PyAMQP** (`azure.eventhub._pyamqp.ReceiveClient`) for feedback monitoring
- **PyAMQP** (`azure.eventhub._pyamqp.SendClient`) for C2D message send

**Benefits:** No compilation, cross-platform compatibility, Microsoft-supported, smaller package size (~9MB reduction)

## Dependencies

```python
DEPENDENCIES = [
    ...existing...
    "azure-eventhub~=5.15.0",  # Pure Python AMQP - includes PyAMQP for all AMQP operations
]
```

**Note:** PyAMQP is a pure Python implementation of AMQP 1.0 protocol, bundled within `azure-eventhub`. It does not depend on `uamqp`.

## Implementation Phases

### Phase 1: Event Monitoring

**Scope:** Device telemetry monitoring
- Event monitoring (telemetry from devices) - `azure-eventhub`
- AMQP connection and endpoint building - `azure-eventhub`
- Message parsing - `EventData`

### Phase 2: Feedback Monitoring

**Scope:** Feedback message reception
- Feedback monitoring - `PyAMQP`
- AMQP connection building - `PyAMQP`
- Message parsing - `PyAMQP Message`

### Phase 3: C2D Message Send

**Scope:** Cloud-to-Device message transmission
- C2D messaging send - `PyAMQP`
- AMQP connection building - `PyAMQP`
- Message construction - `PyAMQP Message`

## Commands

- `az iot hub monitor-events` - uses `azure-eventhub`
- `az iot central diagnostics monitor-events` - uses `azure-eventhub`
- `az iot hub monitor-feedback` - uses `PyAMQP`
- `az iot device c2d-message send` - uses `PyAMQP`

## Architecture

### Current Implementation
```
IoT Hub → Built-in EventHub Endpoint → azure-eventhub (AMQP) → CLI
IoT Hub → Feedback Receive → PyAMQP (azure.eventhub._pyamqp) → CLI
IoT Hub → C2D Send → PyAMQP (azure.eventhub._pyamqp) → CLI
```

**PyAMQP Details:**
- Pure Python implementation of AMQP 1.0 protocol
- Part of `azure-eventhub` package (no compilation required)
- Supports all IoT Hub AMQP operations (send, receive, feedback)

## SDK Mapping

| Previous (uamqp) | Current Implementation | Notes |
|-----------------|-------------|-------|
| `uamqp.ConnectionAsync` | `EventHubConsumerClient` | Monitor events |
| `uamqp.ReceiveClientAsync` | `consumer_client.receive()` | Receive telemetry |
| `uamqp.ReceiveClient` (feedback) | `PyAMQPReceiveClient` | Feedback monitoring |
| `uamqp.SendClient` | `PyAMQPSendClient` | C2D send |
| `uamqp.Message` | `EventData` / `PyAMQP Message` | Message objects |
| `uamqp.authentication.SASTokenAsync` | `EventHubSharedKeyCredential` / `PyAMQPCBSAuth` | SAS key auth |
| `uamqp.authentication.JWTTokenAuth` | `AzureCliCredential` / `PyAMQPJWTTokenAuth` | AAD auth (az login) |

## Authentication

The CLI supports authentication via connection string or IoT Hub name:

### Connection String Authentication

Connection strings can be provided via the `--login` flag to avoid session login via `az login`.

**Event Monitoring:**
- Uses `EventHubConsumerClient.from_connection_string()` or `EventHubSharedKeyCredential`
- Standard IoT Hub connection string format
- Example: `--login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'`

**C2D Send / Feedback Monitoring:**
- Uses `PyAMQPCBSAuth` with IoT Hub SAS tokens
- Custom SAS token generation via `SasTokenAuthentication` class
  - IoT Hub requires base64-decoded keys for HMAC signature
  - PyAMQP's built-in `SASTokenAuth` uses raw UTF-8 keys (Event Hub style)
  - Solution: Generate IoT Hub-compatible tokens and pass via CBS authentication

### IoT Hub Name Authentication

When using `--hub-name` (or `-n`) without `--login`, the extension uses Azure CLI authentication.

**Event Monitoring:**
- Uses `AzureCliCredential` (from azure-identity package)
- Standard `TokenCredential` interface
- Requires user to run `az login` first

**C2D Send / Feedback Monitoring:**
- Uses `PyAMQPJWTTokenAuth` with Azure CLI credentials
- Token provider function retrieves JWT from `Profile.get_raw_token()`
- Requires user to run `az login` first

## References

- **azure-eventhub SDK:** https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/eventhub/azure-eventhub
- **azure-eventhub PyPI:** https://pypi.org/project/azure-eventhub/
- **IoT Hub Endpoints Documentation:** https://learn.microsoft.com/en-us/azure/iot-hub/iot-hub-devguide-endpoints
- **IoT Hub C2D Messaging:** https://learn.microsoft.com/en-us/azure/iot-hub/iot-hub-devguide-messages-c2d

## Summary

The Azure IoT CLI extension uses pure Python AMQP implementations:
- Event monitoring → `azure-eventhub` (EventHubConsumerClient)
- Feedback monitoring → PyAMQP (azure.eventhub._pyamqp.ReceiveClient)
- C2D message send → PyAMQP (azure.eventhub._pyamqp.SendClient)
- Message parsing → EventData / PyAMQP Message
- Authentication → EventHub credentials / PyAMQP CBS/JWT authentication

PyAMQP is a pure Python implementation of AMQP 1.0 protocol bundled within `azure-eventhub`. It provides all AMQP functionality without requiring C-based dependencies.
