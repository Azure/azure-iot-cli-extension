#!/usr/bin/env bash
set -e

proc_number=`python -c 'import multiprocessing; print(multiprocessing.cpu_count())'`

# Run pylint/flake8 on IoT extension
pylint azext_iot/ --ignore=models,service_sdk,device_sdk,custom_sdk,dps_sdk,events3 --rcfile=./.pylintrc -j $proc_number
flake8 --statistics --exclude=*_sdk,events3 --append-config=./.flake8 azext_iot/
