#!/usr/bin/env bash
set -e

proc_number=`python -c 'import multiprocessing; print(multiprocessing.cpu_count())'`

# Run pylint/flake8 on IoT extension
pylint azext_iot/ --ignore=models,service_sdk,device_sdk,custom_sdk,dps_sdk,pnp_sdk --rcfile=./.pylintrc -j $proc_number
flake8 --statistics --exclude=*_sdk --append-config=./.flake8 azext_iot/
