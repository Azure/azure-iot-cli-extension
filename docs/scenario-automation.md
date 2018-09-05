## Automation Scenarios

This section aims to provide the community with example automation scripts using the CLI IoT extension in order to jump start Azure IoT scenario ideas.



### Provision, simulate and monitor devices

```bash
#!/usr/bin/env bash

# -----------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# -----------------------------------------------------------------------------

# This bash script will provision, simulate and monitor device telemetry.
# Before execution set the IOTHUB_CONNSTRING and IOTHUB_NUM_DEVICES env vars.

trap "exit" INT TERM
trap "kill 0" EXIT

iothub_connstring=$IOTHUB_CONNSTRING
num_devices=$IOTHUB_NUM_DEVICES

echo "Received IoT Hub connstring: $iothub_connstring"
echo "Number of devices to create: $num_devices"

create_device="iot hub device-identity create --login $iothub_connstring -d "
sim_device="iot device simulate --login $iothub_connstring -d "
monitor_events="iot hub monitor-events --login $iothub_connstring -y -t 10 "

device_names=()

for i in `seq 1 $num_devices`;
do
    uuid=$(cat /proc/sys/kernel/random/uuid)
    c="$create_device$uuid"
    az $c
    device_names+=($uuid)
done


for name in ${device_names[@]}
do
    interval=$(((RANDOM % 5) + 1))
    c="$sim_device$name -mi $interval"
    (az $c &) > /dev/null
done

az $monitor_events

```
