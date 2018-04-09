#!/usr/bin/env bash
set -e

proc_number=`python -c 'import multiprocessing; print(multiprocessing.cpu_count())'`

# Run pylint/flake8 on IoT extension
pylint azext_iot/ --ignore=models,device_msg_sdk,device_query_sdk,device_twin_sdk,dps_sdk,modules_sdk,events3 --rcfile=./.pylintrc -j $proc_number
flake8 --statistics --exclude=*_sdk,events3 --append-config=./.flake8 azext_iot/
