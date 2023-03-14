# Tox Testing Guide

[Tox](https://tox.wiki/) is a CLI tool used to run various python testing environments with specific dependencies.

Currently, our testing matrix is broken up into the following groups:

- Python versions to run tests:
    - 3.7 (support ends 2023-06-27)
    - 3.8
    - 3.9
    - 3.10
    - 3.11
- Azure CLI Core versions to test extension against:
    - `azmin` installs the minimum supported CLI version (currently `2.32.0`)
    - `azcur` installs the latest released CLI version from PyPi
    - `azdev` installs the CLI from your local CLI instance (located at `../azure-cli`) 
- Types of tests to run:
    - Linting / style only
    - Unit tests
    - Integration tests


## Running Tox Locally
In order to run tox testing environments as currently configured, you must install tox (currently in `dev_requirements`, so already part of dev setup) and have the azure-cli repo cloned alongside your extension repo:
    
    ./azure-cli
    ./azure-iot-cli-extension

Environment strings can be passed to tox with `-e "env"` for a single environment, or `-e "env1, env2"` for multiple environments.

If you need to add additional inputs to `pytest` - you can do so by using `--` as a separator, like below (only test last failed, very verbose):
 
        `tox -e "python-azdev-unit" -- --lf --vv`

The first time you run a new environment in tox, it will perform some setup tasks and dependency installation which will incur some overhead, but ensuing test runs will be able to skip this step. 

- Tox can detect dependency / command changes in tox.ini and other related settings, but does not check files external to tox (code, dev_requirements, etc). 

- In order to rebuild a tox environment, you need to run tox with the `-r` switch.

The [current tox config](../tox.ini) supports local test configurations for the following environments:

- Linting
  - To run flake8 and pylint locally on your code, simply run:
    
        tox -e lint

- Various Python and AZ CLI Versions
  - The tox environment string (passed to `-e`) will be parsed as such:
    
        py{thon,3.7...3.11}-az{min,cur,dev}-{int,unit}

    |Python version | CLI version   | Test type     |
    |---------------|---------------|---------------|
    |"python"|"azmin"|"int"|
    |"py3.7"|"azcur"|"unit"|
    |"py3.8"|"azdev"||
    |"py3.9"|||
    |"py3.10"|||
    |"py3.11"|||

**If you choose not to select a specific python version (which is also the current default), you can use `python` instead, to invoke whichever interpreter version `python` invokes in your environment.**



### Tox Environment Selection Examples:

    tox -e "lint, python-azdev-unit"
        - Default if you run `tox` with no arguments 
        - Run linters, current python/dev CLI unit tests
    tox -e "python-azdev-int"
        - Current python interpreter, local azure CLI install, integration tests
    tox -e "py3.7-azmin-unit"
        - Python 3.7, min supported CLI, unit tests
    tox -e "py{3.7,3.11}-az{min,cur}-unit"
        - Python 3.7, min supported CLI core, unit tests
        - Python 3.7, currently released CLI core, unit tests
        - Python 3.11, min supported CLI core, unit tests
        - Python 3.11, currently released CLI core, unit tests


In order to list all recognized environments, you can type `tox -av`, which will display them all in a list:
    
![image](https://user-images.githubusercontent.com/13545962/217683727-1ec36d2c-e055-4677-a5a9-8f87cdcc987b.png)

