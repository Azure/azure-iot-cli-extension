#!/usr/bin/env pwsh

# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# Setup
$resource_group_name = $args[0]
if ($args[1]) {
    $iothub_name = $args[1]
}
else {
    Write-Host "`r`nCreating IoT Hub for running smoke tests..."
    $iothub_name = "smoketest-hub-$(New-Guid)"
    az iot hub create -g $resource_group_name --name $iothub_name --sku S1
}

if ($args[2]) {
    $dps_name = $args[2]
}
else {
    Write-Host "`r`nProvisioning DPS for running smoke tests..."
    $dps_name = "smoketest-dps-$(New-Guid)"
    az iot dps create -g $resource_group_name --name $dps_name
}

$hub_module_id = "smoke-test-module"
$hub_config_name = "smoke-test-config"
$hub_config_content = "`"{'moduleContent': {'properties.desired.chillerWaterSettings': {'temperature': 38, 'pressure': 78}}}`""

$device_id = "smoke-test-device"
$desired_twin_properties = "`"{'conditions':{'temperature':{'warning':70, 'critical':100}}}`""

$edge_deployment_name = "smoke-test-deployment"
$edge_deployment_content = "scripts/smoke_tests/edge_deployment_content.json"
$edge_deployment_metrics = "`"{'queries':{'mymetric':'SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200'}}`"" 
$edge_deployment_condition = "`"tags.environment='dev'`""
$edge_module_content = "scripts/smoke_tests/edge_module_content.json"

$dps_registration_id = "smoke-test-dps-registration"
$dps_enrollment_id = "smoke-test-dps-enrollment"
$dps_enrollment_group_id = "smoke-test-dps-enrollment-group"
$dps_endorsement_key = "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1QQsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRIDj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzBQQ1NpOJVhrsTrhyJzO7KNw=="

$dt_instance_name = "smoketest-dt-$(New-Guid)"
$dt_location = "westus2"
$dt_eventgrid_endpoint = "smoketest-dt-eventgrid-endpoint"
$dt_eventgrid_topic = "smoketest-dt-eventgrid-topic"
$dt_eventgrid_secret = "https://accountname.blob.core.windows.net/containerName?sasToken"
$dt_connection_name = "smoketest-dt-connection"
$dt_route_name = "smoketest-dt-route"
$dtmi_model_content = "scripts/smoke_tests/dtmi_model.json"
$dtmi_target_model_content = "scripts/smoke_tests/Room.json"
$dt_twin_id = "smoketest-dt-twin"
$dt_target_twin_id = "smoketest-dt-target-twin"
$dt_twin_relationship_id = "smoketest-dt-twin-relationship"

# DT Setup
Write-Host "`r`nSetting up environment to run digital twin commands..."
az dt create -n $dt_instance_name -g $resource_group_name -l $dt_location
az eventgrid topic create --name $dt_eventgrid_topic --resource-group $resource_group_name -l $dt_location

$commands = @()

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
$commands += "az iot device c2d-message receive -g $resource_group_name -d $device_id -n $iothub_name -g $resource_group_name --complete"
$commands += "az iot device send-d2c-message -g $resource_group_name -n $iothub_name -d $device_id --data 'Test Message'"

# IoT Edge
$commands += "az iot edge set-modules -g $resource_group_name --hub-name $iothub_name --device-id $device_id --content $edge_module_content"
$commands += "az iot edge deployment create -g $resource_group_name -d $edge_deployment_name -n $iothub_name --content $edge_deployment_content --target-condition $edge_deployment_condition --priority 10 --metrics $edge_deployment_metrics --layered"
$commands += "az iot edge deployment show -g $resource_group_name -d $edge_deployment_name -n $iothub_name"

# IoT DPS
$commands += "az iot dps compute-device-key -g $resource_group_name --key $dps_endorsement_key --registration-id $dps_registration_id"
$commands += "az iot dps enrollment-group create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment-group show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id --attestation-type tpm --endorsement-key $dps_endorsement_key"
$commands += "az iot dps enrollment show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps registration list -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps connection-string show -g $resource_group_name --dps-name $dps_name --all"

# Digital Twins
$commands += "az dt show -n $dt_instance_name"

$commands += "az dt endpoint create eventgrid -n $dt_instance_name -g $resource_group_name --egg $resource_group_name --egt $dt_eventgrid_topic --en $dt_eventgrid_endpoint --dsu $dt_eventgrid_secret"
$commands += "az dt endpoint wait --created -n $dt_instance_name -g $resource_group_name --en $dt_eventgrid_endpoint --interval 1"

$commands += "az dt route create -n $dt_instance_name -g $resource_group_name --endpoint-name $dt_eventgrid_endpoint --route-name $dt_route_name"
$commands += "az dt route show -n $dt_instance_name --route-name $dt_route_name"

$commands += "az dt model create -n $dt_instance_name --models $dtmi_model_content"
$commands += "az dt model show -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1' --definition"

$commands += "az dt twin create -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1' --twin-id $dt_twin_id"
$commands += "az dt twin show -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt twin query -n $dt_instance_name -q 'select * from digitaltwins' --show-cost"
$commands += "az dt twin telemetry send -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt model create -n $dt_instance_name --models $dtmi_target_model_content"
$commands += "az dt twin create -n $dt_instance_name --dtmi 'dtmi:com:example:Room;1' --twin-id $dt_target_twin_id"
$commands += "az dt twin relationship create -n $dt_instance_name --relationship-id $dt_twin_relationship_id --relationship contains --twin-id $dt_twin_id --target $dt_target_twin_id"
$commands += "az dt twin relationship show -n $dt_instance_name --twin-id $dt_twin_id --relationship-id $dt_twin_relationship_id"

# Resource Cleanup
$commands += "az dt model delete -n $dt_instance_name --dtmi 'dtmi:com:example:Floor;1'"
$commands += "az dt model delete -n $dt_instance_name --dtmi 'dtmi:com:example:Room;1'"
$commands += "az dt twin relationship delete-all -n $dt_instance_name --twin-id $dt_twin_id -y"
$commands += "az dt twin delete -n $dt_instance_name --twin-id $dt_twin_id"
$commands += "az dt twin delete -n $dt_instance_name --twin-id $dt_target_twin_id"
$commands += "az dt route delete -n $dt_instance_name --route-name $dt_route_name"
$commands += "az dt endpoint delete -n $dt_instance_name -g $resource_group_name --en $dt_eventgrid_endpoint -y"
$commands += "az eventgrid topic delete --name $dt_eventgrid_topic --resource-group $resource_group_name"
$commands += "az dt reset -n $dt_instance_name -y"
$commands += "az dt delete -n $dt_instance_name -y"
$commands += "az iot hub module-identity delete -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub configuration delete -g $resource_group_name -c $hub_config_name -n $iothub_name"
$commands += "az iot hub device-identity delete -g $resource_group_name -n $iothub_name -d $device_id"
$commands += "az iot edge deployment delete -g $resource_group_name -d $edge_deployment_name -n $iothub_name"
$commands += "az iot dps enrollment delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps enrollment-group delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"

Write-Host "`r`nRunning smoke test commands...`r`n"

# Execute commands
foreach ($command in $commands) {
    Write-Host "`r`nExecuting command:`r`n$command"
    Invoke-Expression "$command --only-show-errors"
}

# IoT Hub needs to be deleted if it was created for running smoke tests
if (!$args[1]) {
    Write-Host "`r`nDeleting the temporarily created IoT Hub..."
    az iot hub delete -g $resource_group_name --name $iothub_name
}

if (!$args[2]) {
    Write-Host "`r`nDeleting the temporarily provisioned DPS instance..."
    az iot dps delete -g $resource_group_name --name $dps_name
}

Write-Host "`r`nSmoke testing complete."