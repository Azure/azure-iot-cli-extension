# Contributing

## Dev Setup

1. Get Python 3: https://www.python.org/downloads/

### Required Repositories

You must fork and clone the repositories below. Follow the videos and instructions found [here](https://github.com/Azure/azure-cli-dev-tools#setting-up-your-development-environment).

1. https://github.com/Azure/azure-cli

2. https://github.com/Azure/azure-iot-cli-extension

> IMPORTANT: When cloning the repositories and environments, ensure they are all siblings to each other. This makes things much easier down the line.

```text
source-directory/
|-- azure-cli/
|-- azure-iot-cli-extension/
|-- .env3/
```

> IMPORTANT: Ensure you keep the Python virtual environment you created above. It is required for development.

After following the videos, ensure you have:

1. Python virtual environment

2. Functional development az cli

#### Environment Variables

You can run this setup in `bash` or `cmd` environments, this documentation just show the `powershell` flavor.

1. Create a directory for your development extensions to live in

    ```powershell
    mkdir path/to/source/extensions/azure-iot
    ```

2. Set `AZURE_EXTENSION_DIR` to the following

    ```powershell
    $env:AZURE_EXTENSION_DIR="path/to/source/extensions"
    ```

#### azdev Steps

Similar to the video, have your virtual environment activated then execute the following command

```powershell
(.env3) azdev setup -c path/to/source/azure-cli
```

#### Install dev extension

1. Change directories

    ```powershell
    cd path/to/source/azure-iot-cli-extension
    ```

2. Install the extension (should only be needed once)

    ```powershell
    pip install -U --target path/to/source/extensions/azure-iot .
    ```

#### Verify environment is setup correctly

Run a command that is present in the iot extension space

```powershell
az iot central app -h
```

If this works, then you should now be able to make changes to the extension and have them reflected immediately in your az cli.

## Unit and Integration Testing

### Unit Tests

You may need to install the dev_requirements for this

```powershell
pip install -r path/to/source/dev_requirements
```

Example unit tests runs:

_Hub:_
`pytest azext_iot/tests/iothub/core/test_iot_ext_unit.py`

_DPS:_
`pytest azext_iot/tests/dps/core/test_dps_discovery_unit.py`

Unit tests end in "_unit" so execute the following command to run all unit tests,
`pytest -k "_unit"`

Execute the following command to run the IoT Hub unit tests:

`pytest azext_iot/tests/iothub/ -k "_unit"`

### Integration Tests

Integration tests are run against Azure resources and depend on environment variables.

#### Azure Resource Setup

The following resources will be needed for the integration tests.

- IoT Hub
- IoT Device Provisioning Service
- IoT Digital Twin
- IoT Central App
- Storage Account (with an empty Container)
- Event Grid Topic
- Event Hub Namespace with an Event Hub
- Service Bus Namespace with a Topic
- Azure Data Explorer Cluster with a Database

If specified in the pytest.ini configuration file, those resources will be used. Please ensure that the resources are in a clean, new state (ex: Iot Hub should not have any devices). Otherwise, new resources will be generated during the test startup and deleted during the test teardown.

Note that if you stop the code with ctrl + C, the resources may not be deleted properly.

#### Integration Test Environment Variables

You can either manually set the environment variables or use the `pytest.ini.example` file in the root of the extension repo. To use that file, rename it to `pytest.ini`, open it and set the variables as indicated below.

```
    AZURE_TEST_RUN_LIVE=True
    azext_iot_testrg=
    azext_iot_testhub=
    azext_iot_testdps=
    azext_iot_teststorageaccount=
    azext_iot_teststoragecontainer=
    azext_iot_central_app_id=
    azext_iot_central_scope_id=
    azext_iot_central_primarykey=
    azext_iot_central_storage_cstring=
    azext_iot_central_storage_container=
    azext_dt_adx_cluster=
    azext_dt_adx_database=
    azext_dt_adx_rg=
    azext_dt_ep_eventgrid_topic=
    azext_dt_ep_servicebus_namespace=
    azext_dt_ep_servicebus_policy=
    azext_dt_ep_servicebus_topic=
    azext_dt_ep_eventhub_namespace=
    azext_dt_ep_eventhub_policy=
    azext_dt_ep_eventhub_topic=
    azext_dt_ep_eventhub_topic_consumer_group=
    azext_dt_ep_rg=
    azext_dt_region=
```

To run almost all of the tests, only the `azext_iot_testrg` is needed.

To run all tests, `azext_iot_testrg`, `azext_iot_central_app_id`, and `azext_iot_central_primarykey` are needed because the IoT Central Primary Key cannot be currently retrieved through the CLI.

For all resources, if the environmental variable is not provided, a new instance will be created for the test run and deleted at the end of the test run.

##### General Variables

`az_iot_testrg` is the resource group that contains the IoT Hub and DPS instances or where all test resources are created. This is required, as it will be the default resource group if any other resource group variables are not provided.

`azext_iot_testhub` is the test IoT Hub name. Optional variable, used for IoT Hub and DPS tests. If not provided, a new IoT Hub will be created for the test run (and deleted at the end of the test).

`azext_iot_testdps` is the test DPS name. Optional variable used for IoT DPS tests. If not provided, a new DPS instance will be created for the test run (and deleted at the end of the test).

`azext_iot_teststorageaccount` is the storage account used for running IoT Hub and Central storage tests. Optional variable, specify only when you want to run storage tests. During these tests, your hub will be assigned a System-Assigned AAD identity, and will be granted the role of "Storage Blob Data Contributor" on the storage account you provide. Both the hub's identity and the RBAC role will be removed once the test completes. No role assignments are made for the IoT Central App.

`azext_iot_teststoragecontainer` is the name of blob container belonging to the above mentioned storage account. Optional environment variable, defaults to 'devices' when not specified.

##### IoT Central Test variables

`azext_iot_central_app_id` is the IoT Central Application Id or name. Optional variable, used for IoT Central tests.

`azext_iot_central_scope_id` is the ID scope for the DPS associated with the IoT Central Application. Optional variable, used for IoT Central tests.

`azext_iot_central_token` is the api token to use for the IoT Central Application. Optional variable, only used to populate --token argument in IoT Central commands.

`azext_iot_central_dns_suffix` is the DNS Suffix to use for the IoT Central Application. Optional variable, only used to populate --central-dns-suffix argument in IoT Central commands.

`azext_iot_central_primarykey` is the IoT Central Application Id or name. Optional variable, used for IoT Central tests. Cannot be currently retrieved through the CLI.

`azext_iot_central_storage_container` is the name of blob container belonging to the `azext_iot_teststorageaccount` storage account. Optional environment variable, defaults to 'central' when not specified.

##### Digital Twin Test variables

`azext_dt_region` is the region to restrict Digital Twins creation. Optional variable, if not specified, will create the Digital Twins in a supported region.

`azext_dt_adx_cluster` is the name of the Azure Data Explorer Cluster to use. Optional variable, used for Digital Twin data history tests. Azure Data Explorer Cluster creation time can take up to 20 minutes, so having a cluster is recommended.

`azext_dt_adx_database` is the name of the database in the Azure Data Explorer Cluster to use. Optional variable, used for Digital Twin data history tests.

`azext_dt_adx_rg` is the resource group that contains the Azure Data Explorer Cluster. If not provided, `az_iot_testrg` will be used as the resource group.

`azext_dt_ep_eventgrid_topic` is the Event Grid Topic to use. Optional variable, used for Digital Twin endpoint tests.

`azext_dt_ep_servicebus_namespace` is the Service Bus Namespace to use. Optional variable, used for Digital Twin endpoint tests.

`azext_dt_ep_servicebus_policy` is the policy for the topic in the Service Bus Namespace to use. Optional variable, used for Digital Twin endpoint tests.

`azext_dt_ep_servicebus_topic` is the topic in the Service Bus Namespace to use. Optional variable, used for Digital Twin endpoint tests.

`azext_dt_ep_eventhub_namespace` is the Event Hub Namespace to use. Optional variable, used for Digital Twin endpoint and data history tests.

`azext_dt_ep_eventhub_policy` is the policy for the Event Hub instance in the Event Hub Namespace to use. Optional variable, used for Digital Twin endpoint and data history tests.

`azext_dt_ep_eventhub_topic` is the Event Hub instance in the Event Hub Namespace to use. Optional variable, used for Digital Twin endpoint and data history tests.

`azext_dt_ep_eventhub_topic_consumer_group` is the Service Bus Namespace to use. Optional variable, used for Digital Twin data history tests.

`azext_dt_ep_rg` is the resource group that contains the endpoint (Event Hub, Event Grid, Service Bus) variables. Optional variable, if not provided, `az_iot_testrg` will be used as the resource group.

##### IoT Hub

Execute the following command to run the IoT Hub integration tests:

`pytest azext_iot/tests/iothub/ -k "_int.py"`

##### Device Provisioning Service

Execute the following command to run the IoT Hub DPS integration tests:

`pytest azext_iot/tests/dps/ -k "_int.py"`

##### IoT Central
Execute the following command to run the IoT Central integration tests:

`pytest azext_iot/tests/central/ -k "_int.py"`

IoT Central integration tests can be run against all available api versions using command line argument "--api-version"

e.g. run tests against v 1.0

`pytest azext_iot/tests/central/ -k "_int.py" --api-version "1.0"`

If the "--api-version" argument is not specified, all runs act against default api version for each tested command.
#### Unit and Integration Tests Single Command

Execute the following command to run both Unit and Integration tests and output a code coverage report to the console and to a `.coverage` file.  You can configure code coverage with the `.coveragerc` file.

`pytest -v . --cov=azext_iot --cov-config .coveragerc`

#### Formatting and Linting

The repo uses the linter in `azdev`.

To install the required version of azdev, run this command:

```powershell
pip install -e "git+https://github.com/Azure/azure-cli@dev#egg=azure-cli-dev-tools&subdirectory=tools"
```

To run the linter, run this command:

```powershell
azdev cli-lint --ci --extensions azure-iot
```

We use our flake8 and pylint rules. We recommend you set up your IDE as per the VSCode setup below for best compliance.

We are also starting to use `python black`. To set this up on VSCode, see the following blog post.

https://medium.com/@marcobelo/setting-up-python-black-on-visual-studio-code-5318eba4cd00

## Optional

### VSCode setup

1. Install VSCode

2. Install the required extensions
    * ([ms-python.python](https://marketplace.visualstudio.com/items?itemName=ms-python.python) is recommended)

3. Set up `settings.json`

    ```json
    {
        "python.pythonPath": "path/to/source/env3/Scripts/python.exe",
        "python.venvPath": "path/to/source/",
        "python.linting.pylintEnabled": true,
        "python.autoComplete.extraPaths": [
            "path/to/source/env3/Lib/site-packages"
        ],
        "python.linting.flake8Enabled": true,
        "python.linting.flake8Args": [
            "--config=setup.cfg"
        ],
        "files.associations": {
            "*/.azure-devops/.yml": "azure-pipelines"
        }
    }
    ```

4. Set up `launch.json`

    ```json
    {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Azure CLI Debug (Integrated Console)",
                "type": "python",
                "request": "launch",
                "pythonPath": "${config:python.pythonPath}",
                "program": "${workspaceRoot}/../azure-cli/src/azure-cli/azure/cli/__main__.py",
                "cwd": "${workspaceRoot}",
                "args": [
                    "--help"
                ],
                "console": "integratedTerminal",
                "debugOptions": [
                    "WaitOnAbnormalExit",
                    "WaitOnNormalExit",
                    "RedirectOutput"
                ],
                "justMyCode": false
            }
        ]
    }
    ```

    * launch.json was derived from [this](https://raw.githubusercontent.com/Azure/azure-cli/dev/.vscode/launch.json) file

    * Note: your "program" path might be different if you did not set up the folder structure as siblings as recommended above

    * Note: when passing args, ensure they are all comma separated.

    Correct:

    ```json
    "args": [
        "--a", "value", "--b", "value"
    ],
    ```

    Incorrect:

    ```json
    "args": [
        "--a value --b value"
    ],
    ```

5. Set up python black.

6. You should now be able to place breakpoints in VSCode and see execution halt as the code hits them.

### Python debugging

https://docs.python.org/3/library/pdb.html

1. `pip install pdbpp`
2. If you need a breakpoint, put `import pdb; pdb.set_trace()` in your code
3. Run your command, it should break execution wherever you put the breakpoint.

## Microsoft CLA

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.
