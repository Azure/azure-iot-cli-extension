#!/usr/bin/env pwsh

# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# Setup
if (!$args[0]) {
    Write-Error -Message "Error: Resource group argument is mandatory to run the script." -Category InvalidArgument
    exit 1
}
$resource_group_name = $args[0]
$run_id = $(New-Guid)

if ($args[1]) {
    $central_app_id = $args[1]
}
else {
    Write-Host "`r`nCreating IoT Central App for running smoke tests..."
    $central_app_id = "smoketest-app-$run_id"
    az iot central app create -g $resource_group_name --name $central_app_id --subdomain $central_app_id -l eastus2
}

if ($args[2]) {
    $iothub_name = $args[2]
}
else {
    Write-Host "`r`nCreating IoT Hub for running smoke tests..."
    $iothub_name = "smoketest-hub-$run_id"
    az iot hub create -g $resource_group_name --name $iothub_name --sku S1
}

if ($args[3]) {
    $dps_name = $args[3]
}
else {
    Write-Host "`r`nProvisioning DPS for running smoke tests..."
    $dps_name = "smoketest-dps-$run_id"
    az iot dps create -g $resource_group_name --name $dps_name
}

$hub_module_id = "smoke-test-module"
$hub_config_name = "smoke-config-$run_id"
$hub_config_content = "`"{'moduleContent': {'properties.desired.chillerWaterSettings': {'temperature': 38, 'pressure': 78}}}`""

$device_id = "smoke-device-$run_id"
$desired_twin_properties = "`"{'conditions':{'temperature':{'warning':70, 'critical':100}}}`""

$edge_deployment_name = "smoke-deploy-$run_id"
$edge_deployment_content = "scripts/smoke_tests/edge_deployment_content.json"
$edge_deployment_metrics = "`"{'queries':{'mymetric':'SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200'}}`""
$edge_deployment_condition = "`"tags.environment='dev'`""
$edge_module_content = "scripts/smoke_tests/edge_module_content.json"

$dps_registration_id = "smoke-reg-$run_id"
$dps_enrollment_id = "smoke-enroll-$run_id"
$dps_enrollment_group_id = "smoke-enr-grp-$run_id"
$dps_endorsement_key = "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1QQsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRIDj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzBQQ1NpOJVhrsTrhyJzO7KNw=="

$dt_instance_name = "smoketest-dt-$run_id"
$dt_location = "westus2"
$dt_eventgrid_endpoint = "smoketest-dt-eventgrid-endpoint"
$dt_eventgrid_topic = "smoketest-dt-eventgrid-topic"
$dt_eventgrid_secret = "https://accountname.blob.core.windows.net/containerName?sasToken"
$dt_route_name = "smoketest-dt-route"
$dtmi_model_content = "scripts/smoke_tests/dtmi_model.json"
$dtmi_target_model_content = "scripts/smoke_tests/Room.json"
$dt_twin_id = "smoketest-dt-twin"
$dt_target_twin_id = "smoketest-dt-target-twin"
$dt_twin_relationship_id = "smoketest-dt-twin-relationship"

$central_device_template_id = "dtmi:id_$run_id".Replace("-", "_")
$central_device_template_content = "scripts/smoke_tests/central_device_template.json"
$central_device_id = "smoke-central-$run_id"
$central_device_name = "smoke-test-central-device-name"
$central_device_command = "testRootCommand"
$central_device_command_payload = "`"{'request':{'argument':'value'}}`""
$central_device_query = "SELECT TOP 1 testDefaultCapability FROM $central_device_template_id WHERE WITHIN_WINDOW(PT1H)"
$central_api_token_id = "tid-$run_id"
$central_org = "smoke-test-central-org"
$central_export_id = "smoke-export-$run_id"
$central_export_destination_id = "smoke-dest-$run_id"
$central_export_destinations_json = "`"[{'id' : '$central_export_destination_id'}]`""

# DT Setup
Write-Host "`r`nCreating digital twins instance and eventgrid topic..."
az dt create -n $dt_instance_name -g $resource_group_name -l $dt_location
az eventgrid topic create --name $dt_eventgrid_topic --resource-group $resource_group_name -l $dt_location

$commands = @()

# Device Update
$adu_account_name = ("smoke-adu-" + (New-Guid).guid.replace("-","")).substring(0,23)
$commands += "az iot du account create -n $adu_account_name -g $resource_group_name -l eastus2euap"
$commands += "az iot du account list"
$commands += "az iot du account show -n $adu_account_name"
$commands += "az iot du account delete -g $resource_group_name -n $adu_account_name --no-wait -y"

# IoT Hub
$commands += "az iot hub connection-string show -g $resource_group_name -n $iothub_name --all"

# IoT Hub Configuration
$commands += "az iot hub configuration create -g $resource_group_name -c $hub_config_name -n $iothub_name --content $hub_config_content --target-condition 'from devices.modules where tags.building=9' --priority 1"
$commands += "az iot hub configuration show -g $resource_group_name -c $hub_config_name -n $iothub_name"

# IoT Hub Device
$commands += "az iot hub device-identity create -g $resource_group_name -n $iothub_name -d $device_id --ee"
$commands += "az iot hub device-identity show -g $resource_group_name -n $iothub_name -d $device_id"
$commands += "az iot hub device-identity renew-key -g $resource_group_name -n $iothub_name -d $device_id --kt primary"
$commands += "az iot hub device-twin show -g $resource_group_name -n $iothub_name -d $device_id"
$commands += "az iot hub device-twin update -g $resource_group_name -n $iothub_name -d $device_id --desired $desired_twin_properties"
$commands += "az iot hub generate-sas-token -g $resource_group_name -d $device_id -n $iothub_name"
$commands += "az iot hub query -g $resource_group_name -n $iothub_name -q 'select * from devices'"

# IoT Hub Module
$commands += "az iot hub module-identity create -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub module-identity show -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub module-twin show -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub module-twin update -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name --desired $desired_twin_properties"

# IoT Device
$commands += "az iot device c2d-message send -g $resource_group_name -d $device_id -n $iothub_name --data 'Hello World' --props 'key0=value0;key1=value1' -y"
$commands += "az iot device c2d-message receive -g $resource_group_name -d $device_id -n $iothub_name --complete"
$commands += "az iot device send-d2c-message -g $resource_group_name -n $iothub_name -d $device_id --data 'Test Message'"

# IoT Edge
$commands += "az iot edge set-modules -g $resource_group_name --hub-name $iothub_name --device-id $device_id --content $edge_module_content"
$commands += "az iot edge deployment create -g $resource_group_name -d $edge_deployment_name -n $iothub_name --content $edge_deployment_content --target-condition $edge_deployment_condition --priority 10 --metrics $edge_deployment_metrics --layered"
$commands += "az iot edge deployment show -g $resource_group_name -d $edge_deployment_name -n $iothub_name"

# Hub Resource Cleanup
$commands += "az iot hub module-identity delete -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub configuration delete -g $resource_group_name -c $hub_config_name -n $iothub_name"
$commands += "az iot hub device-identity delete -g $resource_group_name -n $iothub_name -d $device_id"
$commands += "az iot edge deployment delete -g $resource_group_name -d $edge_deployment_name -n $iothub_name"

# IoT DPS
$commands += "az iot dps compute-device-key -g $resource_group_name --key $dps_endorsement_key --registration-id $dps_registration_id"
$commands += "az iot dps enrollment-group create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment-group show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id --attestation-type tpm --endorsement-key $dps_endorsement_key"
$commands += "az iot dps enrollment show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps registration list -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps connection-string show -g $resource_group_name --dps-name $dps_name --all"

# DPS Resource Cleanup
$commands += "az iot dps enrollment delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps enrollment-group delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"

# Digital Twins
$commands += "az dt show -n $dt_instance_name"

$commands += "az dt endpoint create eventgrid -n $dt_instance_name -g $resource_group_name --egg $resource_group_name --egt $dt_eventgrid_topic --en $dt_eventgrid_endpoint --dsu $dt_eventgrid_secret"
$commands += "az dt endpoint wait --created -n $dt_instance_name -g $resource_group_name --en $dt_eventgrid_endpoint --interval 1"

$commands += "az dt route create -n $dt_instance_name -g $resource_group_name --endpoint-name $dt_eventgrid_endpoint --route-name $dt_route_name"
$commands += "az dt route show -g $resource_group_name -n $dt_instance_name --route-name $dt_route_name"

$commands += "az dt model create -g $resource_group_name -n $dt_instance_name --models $dtmi_model_content"
$commands += "az dt model show -g $resource_group_name -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1' --definition"

$commands += "az dt twin create -g $resource_group_name -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1' --twin-id $dt_twin_id"
$commands += "az dt twin show -g $resource_group_name -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt twin query -g $resource_group_name -n $dt_instance_name -q 'select * from digitaltwins' --show-cost"
$commands += "az dt twin telemetry send -g $resource_group_name -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt model create -g $resource_group_name -n $dt_instance_name --models $dtmi_target_model_content"
$commands += "az dt twin create -g $resource_group_name -n $dt_instance_name --dtmi 'dtmi:com:example:Room;1' --twin-id $dt_target_twin_id"
$commands += "az dt twin relationship create -g $resource_group_name -n $dt_instance_name --relationship-id $dt_twin_relationship_id --relationship contains --twin-id $dt_twin_id --target $dt_target_twin_id"
$commands += "az dt twin relationship show -g $resource_group_name -n $dt_instance_name --twin-id $dt_twin_id --relationship-id $dt_twin_relationship_id"

# Digital Twins Resource Cleanup
$commands += "az dt model delete -g $resource_group_name -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1'"
$commands += "az dt model delete -g $resource_group_name -n $dt_instance_name --dtmi 'dtmi:com:example:Room;1'"
$commands += "az dt twin relationship delete-all -g $resource_group_name -n $dt_instance_name --twin-id $dt_twin_id -y"
$commands += "az dt twin delete -g $resource_group_name -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt twin delete -g $resource_group_name -n $dt_instance_name --twin-id $dt_target_twin_id"
$commands += "az dt route delete -g $resource_group_name -n $dt_instance_name --route-name $dt_route_name"
$commands += "az dt endpoint delete -n $dt_instance_name -g $resource_group_name --en $dt_eventgrid_endpoint -y"
$commands += "az eventgrid topic delete -g $resource_group_name --name $dt_eventgrid_topic --resource-group $resource_group_name"
$commands += "az dt reset -g $resource_group_name -n $dt_instance_name -y"
$commands += "az dt delete -g $resource_group_name -n $dt_instance_name -y"

# IoT Central
$commands += "az iot central device-template create --app-id $central_app_id --device-template-id $central_device_template_id --content $central_device_template_content"
$commands += "az iot central device-template show --app-id $central_app_id --device-template-id $central_device_template_id"

$commands += "az iot central device create --app-id $central_app_id --device-id $central_device_id --template $central_device_template_id --simulated"
# Sleeping to ensure device creation is completed
$commands += "Start-Sleep -s 30"
$commands += "az iot central device update --app-id $central_app_id --device-id $central_device_id --device-name $central_device_name"
$commands += "az iot central device show --app-id $central_app_id --device-id $central_device_id"

$commands += "az iot central device command run --app-id $central_app_id --device-id $central_device_id --command-name $central_device_command --content $central_device_command_payload"
$commands += "az iot central device command history --app-id $central_app_id --device-id $central_device_id --command-name $central_device_command"

$commands += "az iot central query --app-id $central_app_id --query-string '$central_device_query'"
$commands += "az iot central export list --app-id $central_app_id"
$commands += "az iot central role list --app-id $central_app_id"
$commands += "az iot central user list --app-id $central_app_id"

$commands += "az iot central api-token create --app-id $central_app_id --token-id $central_api_token_id -r 'operator'"
$commands += "az iot central api-token show --app-id $central_app_id --token-id $central_api_token_id"

$commands += "az iot central organization create --app-id $central_app_id --org-id $central_org"
$commands += "az iot central organization show --app-id $central_app_id --org-id $central_org"

$commands += "az iot central export destination create --app-id $central_app_id --dest-id $central_export_destination_id --type 'webhook@v1' --name 'Smoke Test Export Destination' --url 'https://microsoft.sharepoint.com/'"
$commands += "az iot central export destination show --app-id $central_app_id --dest-id $central_export_destination_id"
$commands += "az iot central export create --app-id $central_app_id --export-id $central_export_id --destinations $central_export_destinations_json --name 'Smoke Test Export' --source 'Telemetry'"
$commands += "az iot central export show --app-id $central_app_id --export-id $central_export_id"

$commands += "az iot central diagnostics registration-summary --app-id $central_app_id"

# Central Resource Cleanup
$commands += "az iot central export delete --app-id $central_app_id --export-id $central_export_id"
$commands += "az iot central export destination delete --app-id $central_app_id --dest-id $central_export_destination_id"
$commands += "az iot central organization delete --app-id $central_app_id --org-id $central_org"
$commands += "az iot central api-token delete --app-id $central_app_id --token-id $central_api_token_id"
$commands += "az iot central device delete --app-id $central_app_id --device-id $central_device_id"
$commands += "az iot central device-template delete --app-id $central_app_id --device-template-id $central_device_template_id"
$commands += "az iot central export delete --app-id $central_app_id --export-id $central_export_id"

# Fetch connection strings
$hub_connection = az iot hub connection-string show -g $resource_group_name -n $iothub_name | ConvertFrom-Json
$hub_conn_string = $hub_connection."connectionString"
$dps_connection = az iot dps connection-string show -g $resource_group_name -n $dps_name | ConvertFrom-Json
$dps_conn_string = $dps_connection."connectionString"

# Ensure that hub and dps don't need to be deleted after logging out
if ($args[2] -And $args[3]) {
    # Logout to prevent command execution using credentials
    $commands += "az logout"

    # Execute Commands using connection string
    $commands += "az iot edge deployment create -g $resource_group_name -d $edge_deployment_name --auth-type 'login' -l '$hub_conn_string' --content $edge_deployment_content --target-condition $edge_deployment_condition --priority 10 --metrics $edge_deployment_metrics --layered"
    $commands += "az iot edge deployment show -g $resource_group_name -d $edge_deployment_name --auth-type 'login' -l '$hub_conn_string'"
    $commands += "az iot dps enrollment-group create -g $resource_group_name --auth-type 'login' -l '$dps_conn_string' --enrollment-id $dps_enrollment_group_id"
    $commands += "az iot dps enrollment-group show -g $resource_group_name --auth-type 'login' -l '$dps_conn_string' --enrollment-id $dps_enrollment_group_id"

    # Cleanup resources created using connection string
    $commands += "az iot edge deployment delete -g $resource_group_name -d $edge_deployment_name --auth-type 'login' -l '$hub_conn_string'"
    $commands += "az iot dps enrollment-group delete -g $resource_group_name --auth-type 'login' -l '$dps_conn_string' --enrollment-id $dps_enrollment_group_id"
}

Write-Host "`r`nRunning smoke test commands...`r`n"

# Execute commands
foreach ($command in $commands) {
    Write-Host "`r`nExecuting command:`r`n$command"
    if ($command -like 'az*') {
        $command += " --only-show-errors"
    }
    Invoke-Expression $command
}


# IoT Central App needs to be deleted if it was created for running smoke tests
if (!$args[1]) {
    Write-Host "`r`nDeleting the temporarily created IoT Central App..."
    az iot central app delete -g $resource_group_name --name $central_app_id -y
}

# IoT Hub needs to be deleted if it was created for running smoke tests
if (!$args[2]) {
    Write-Host "`r`nDeleting the temporarily created IoT Hub..."
    az iot hub delete -g $resource_group_name --name $iothub_name
}

# DPS Instance needs to be deleted if it was created for running smoke tests
if (!$args[3]) {
    Write-Host "`r`nDeleting the temporarily provisioned DPS instance..."
    az iot dps delete -g $resource_group_name --name $dps_name
}

Write-Host "`r`nSmoke testing complete."
