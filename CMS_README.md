# ADR Certificate Management Bug Bash Testing Guide

## Overview

This document provides step-by-step guidance for testing end-to-end control-plane resource setup to enable Certificate Management scenarios between ADR/IoTHub/DPS.

## CLI Installation

[todo] instructions for downloading extension from dist


```bash
az extension remove --name azure-iot --yes
az extension add --source ./path/to/azure-iot.whl --yes
```

## Prerequisites

## Environment Variables Setup (optional)

Set these variables at the beginning of your testing session for convenience.
They're not necessary, but you might thank me later.

### Subscription / Resource Group Configuration
```bash
SUBSCRIPTION_ID="your-subscription-id"
RESOURCE_GROUP="your-resource-group"
LOCATION="centraluseuap"
```
### Resource names (please change these)
```bash
NAMESPACE_NAME="my-namespace"
HUB_NAME="my-hub"
DPS_NAME="my-dps"
USER_IDENTITY="adr-uami"
CUSTOM_ROLE_NAME=""
```

### 1. Create Custom ADR Role

This is a convenience role that assings the superset of DPS/Hub permissions to the principal.

**This resource exists at a subscription level, its name must be unique**
**Please verify if an existing role already satisfies the desired subscription or resource scope**

**Please change the name of this role, and ensure it's configured to your resource-group scope if you are creating it yourself.**

This allows you to share one identity between Hub and DPS that has full permissions to the ADR namespace.

```bash
az role definition create --role-definition '{
  "Name": "'$CUSTOM_ROLE_NAME'",
  "Description": "Custom role for ADR namespace integration",
  "Actions": [
    "Microsoft.DeviceRegistry/namespaces/devices/read",
    "Microsoft.DeviceRegistry/namespaces/devices/write", 
    "Microsoft.DeviceRegistry/namespaces/read",
    "Microsoft.DeviceRegistry/namespaces/write",
    "Microsoft.DeviceRegistry/namespaces/credentials/read",
    "Microsoft.DeviceRegistry/namespaces/credentials/policies/read"
  ],
  "AssignableScopes": ["subscription_or_resource_id"]
}'
```

### 2. Setup IoT Hub RP Contributor Access

```bash
az role assignment create --assignee "89d10474-74af-4874-99a7-c23c2f643083" --role "Contributor" --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"
```

### 3. Create User-Assigned Managed Identity
```bash
az identity create --name $USER_IDENTITY --resource-group $RESOURCE_GROUP --location $LOCATION
UAMI_RESOURCE_ID=$(az identity show --name $USER_IDENTITY --resource-group $RESOURCE_GROUP --query id -o tsv)
```

## Testing Steps

### Step 1: Create ADR Namespace
```bash
az iot adr ns create --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --location $LOCATION
```
*Verify: Namespace created with system-assigned identity (principal ID)*

*Verify: Credential and policy were created*

```bash
az iot adr ns credential show --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
az iot adr ns policy show --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
```

### Step 2: Assign UAMI Role to ADR Namespace
```bash
UAMI_PRINCIPAL_ID=$(az identity show --name $USER_IDENTITY --resource-group $RESOURCE_GROUP --query principalId -o tsv)

NAMESPACE_RESOURCE_ID=$(az iot adr ns show --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)

az role assignment create --assignee $UAMI_PRINCIPAL_ID --role "$CUSTOM_ROLE_NAME" --scope $NAMESPACE_RESOURCE_ID
```

### Step 3: Create IoT Hub with ADR Integration
```bash
az iot hub create --hub-name $HUB_NAME --resource-group $RESOURCE_GROUP --location $LOCATION --sku P1 --mi-user-assigned $UAMI_RESOURCE_ID --ns-resource-id $NAMESPACE_RESOURCE_ID --ns-identity-id $UAMI_RESOURCE_ID
```
*Verify: Hub has correct identity and ADR properties configured*

**Note - if you do not see errors or warnings, please ignore this next section and continue to step 4.**

**If you see error/warning messages about role assignments or permissisons, you will need to manually assign the following roles to the hub for the ADR namespace's system-assigned identity:**

```bash
ADR_PRINCIPAL_ID=$(az iot adr ns show --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --query identity.principalId -o tsv)

HUB_RESOURCE_ID=$(az iot hub show --name $HUB_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)

az role assignment create --assignee $ADR_PRINCIPAL_ID --role "Contributor" --scope $HUB_RESOURCE_ID

az role assignment create --assignee $ADR_PRINCIPAL_ID --role "IoT Hub Registry Contributor" --scope $HUB_RESOURCE_ID
```

### Step 4: Create DPS with ADR Integration
```bash
az iot dps create --name $DPS_NAME --resource-group $RESOURCE_GROUP --location $LOCATION --mi-user-assigned $UAMI_RESOURCE_ID --ns-resource-id $NAMESPACE_RESOURCE_ID --ns-identity-id $UAMI_RESOURCE_ID
```
*Verify: DPS has correct identity and ADR properties configured*

### Step 5: Link Hub to DPS
```bash
az iot dps linked-hub create --dps-name $DPS_NAME --resource-group $RESOURCE_GROUP --hub-name $HUB_NAME
```
*Verify: Hub appears in DPS linked hubs list*

### Step 6: Run ADR Credential Sync
```bash
az iot adr ns credential sync --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
```
*Verify: Command completes without errors*

### Step 7: Validate Hub Certificate
```bash
az iot hub certificate list --hub-name $HUB_NAME --resource-group $RESOURCE_GROUP
```

## Additional Commands to Test

### ADR Namespace Commands
```bash
# List namespaces
az iot adr ns list --resource-group $RESOURCE_GROUP

# Show namespace details
az iot adr ns show --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
```

### ADR Credential Commands  
```bash
# Show credentials
az iot adr ns credential show --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
```

### ADR Policy Commands
```bash
# List policies
az iot adr ns policy list --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP

# Show default policy
az iot adr ns policy show --policy-name "default" --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP

# Create custom policy
az iot adr ns policy create --policy-name "custom-policy" --namespace $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --certificate-key-type "ECC" --certificate-subject "CN=TestDevice"
```

## Cleanup
```bash
az iot adr ns delete --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP
az iot hub delete --name $HUB_NAME --resource-group $RESOURCE_GROUP
az iot dps delete --name $DPS_NAME --resource-group $RESOURCE_GROUP  
az identity delete --name $USER_IDENTITY --resource-group $RESOURCE_GROUP
```
