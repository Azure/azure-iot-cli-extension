# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# Setting this environment variable enables the az command failures to be thrown and not swallowed
$ErrorActionPreference = "Stop"

$resource_group_name = "cli-int-test-rg"
$iothub_name = "smoketest-hub-$(New-Guid)"
$hub_module_id = "smoke-test-module"
$hub_config_name = "smoke-test-config"
$hub_config_content = "`"{'moduleContent': {'properties.desired.chillerWaterSettings': {'temperature': 38, 'pressure': 78}}}`""

$device_id = "smoke-test-device"
$desired_twin_properties = "`"{'conditions':{'temperature':{'warning':70, 'critical':100}}}`""

$edge_deployment_name = "smoke-test-deployment"
$edge_deployment_content = "./edge_deployment_content.json"
$edge_deployment_metrics = "`"{'queries':{'mymetric':'SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200'}}`"" 
$edge_deployment_condition = "`"tags.environment='dev'`""
$edge_module_content = "./edge_module_content.json"

$dps_name = "smoketest-dps-$(New-Guid)"
$dps_registration_id = "smoke-test-dps-registration"
$dps_enrollment_id = "smoke-test-dps-enrollment"
$dps_enrollment_group_id = "smoke-test-dps-enrollment-group"
$dps_endorsement_key = "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1QQsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRIDj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzBQQ1NpOJVhrsTrhyJzO7KNw=="

$commands = @()

# IoT Hub
$commands += "az iot hub create -g $resource_group_name --name $iothub_name --sku S1"
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
$commands += "az iot device c2d-message send -g $resource_group_name -d $device_id -n $iothub_name --data 'Hello World' --props 'key0=value0;key1=value1'"
$commands += "az iot device c2d-message receive -g $resource_group_name -d $device_id -n $iothub_name -g $resource_group_name --complete"
$commands += "az iot device send-d2c-message -g $resource_group_name -n $iothub_name -d $device_id --data 'Test Message'"

# IoT Edge
$commands += "az iot edge set-modules -g $resource_group_name --hub-name $iothub_name --device-id $device_id --content $edge_module_content"
$commands += "az iot edge deployment create -g $resource_group_name -d $edge_deployment_name -n $iothub_name --content $edge_deployment_content --target-condition $edge_deployment_condition --priority 10 --metrics $edge_deployment_metrics --layered"
$commands += "az iot edge deployment show -g $resource_group_name -d $edge_deployment_name -n $iothub_name"

# IoT DPS
$commands += "az iot dps create -g $resource_group_name --name $dps_name"
$commands += "az iot dps compute-device-key -g $resource_group_name --key $dps_endorsement_key --registration-id $dps_registration_id"
$commands += "az iot dps enrollment-group create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment-group show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps enrollment create -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id --attestation-type tpm --endorsement-key $dps_endorsement_key"
$commands += "az iot dps enrollment show -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps connection-string show -g $resource_group_name --dps-name $dps_name --all"

# Resource Cleanup
$commands += "az iot hub module-identity delete -g $resource_group_name -m $hub_module_id -d $device_id -n $iothub_name"
$commands += "az iot hub configuration delete -g $resource_group_name -c $hub_config_name -n $iothub_name"
$commands += "az iot hub device-identity delete -g $resource_group_name -n $iothub_name -d $device_id"
$commands += "az iot edge deployment delete -g $resource_group_name -d $edge_deployment_name -n $iothub_name"
$commands += "az iot dps enrollment delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_id"
$commands += "az iot dps enrollment-group delete -g $resource_group_name --dps-name $dps_name --enrollment-id $dps_enrollment_group_id"
$commands += "az iot dps delete -g $resource_group_name --name $dps_name"
$commands += "az iot hub delete -g $resource_group_name --name $iothub_name"

Write-Host "Running smoke test commands..."

# Execute commands
foreach ($command in $commands) {
    try {
        Invoke-Expression $command -OutVariable standardOut 2>&1 >$null
    }
    catch {
        # Warning should not be considered a failure
        if ($_ -notlike "*warning*" ) {
            az iot dps delete -g $resource_group_name --name $dps_name
            az iot hub delete -g $resource_group_name --name $iothub_name
            Write-Host "Failed to execute command:`r`n$command`r`nAn error occurred:"
            throw
        }
    }
    Write-Host "`r`nSuccessfully executed command:`r`n$command"
    if ($standardOut) {
        $standardOutString = Out-String -InputObject $standardOut
        Write-Host "Output:`r`n$standardOutString"
    }
}

Write-Host "Smoke testing complete."