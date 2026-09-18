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

Tests are organized into folders by resource in `azext_iot\tests\`:
- Central
- Digital Twins
- Device Provisioning Service
- IoT Hub
- Utility

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

Unit tests end in "_unit.py" so execute the following command to run all unit tests,
`pytest -k "_unit.py"`

Execute the following command to run the IoT Hub unit tests:

`pytest azext_iot/tests/iothub/ -k "_unit.py"`

### Integration Tests

Integration tests are run against Azure resources and depend on environment variables.

Example int tests runs:

_Hub:_
`pytest azext_iot/tests/iothub/core/test_iothub_storage_int.py`

_DPS:_
`pytest azext_iot/tests/dps/core/test_dps_discovery_int.py`

The combined Hub/DPS preview's regular DPS phase requires both CSR issuance
variants. They no longer accept pre-created DPS/enrollment/CSR environment
variables. The phase controller owns a dedicated Hub, DPS, and ADR namespace,
links the pair with native bounded propagation recovery, and creates a
service-managed root CA, Microsoft-issued intermediate CA, and leaf policy.
Both variants reuse that infrastructure but generate independent enrollments,
EC keys and CSRs. Bootstrap keys are discovered internally by native registration,
not placed in CLI arguments. Private material is mode 0600 in a temporary mode
0700 directory and is removed even when registration fails. Certificate-chain
encoding/order is not assumed; the response contract remains JSON.

Run the focused local proof from the combined checkout with its prepared tox
environments and extension installed:

```bash
.tox/DPS-phases/bin/python azext_iot/tests/_dps_phase_runner.py \
  --subscription <subscription-id> --resource-group <owned-test-rg> \
  --region centraluseuap --output <new-evidence-directory> --debug-phase regular \
  --debug-node 'azext_iot/tests/dps/device_registration/test_iot_device_registration_int.py::test_register_and_issue_certificate_contract[default]' \
  --debug-node 'azext_iot/tests/dps/device_registration/test_iot_device_registration_int.py::test_register_and_issue_certificate_contract[deadline]'
```

This debug selection is explicitly non-qualifying for the full suite; omit both
debug options for full qualification. Missing or skipped required CSR cases fail
the regular gate. The legacy pinned-resource/cross-platform Azure DevOps template
explicitly excludes these owned-only cases and labels its results partial,
not full DPS qualification. Linux, an authenticated canary-enabled subscription, registered
Microsoft.Devices/Microsoft.DeviceRegistry providers, and permission to manage
the owned resources and their scoped role assignments are required. The regular
admission reserves four DPS slots (three long-lived DPS plus one sequential
capacity case), two S1 Hubs, and one namespace with two CAs/one policy. Only a
validated, nonempty regular debug selection containing exclusively either or
both required CSR nodes reserves one DPS slot, matching its single dedicated
pair. Its admission and cleanup capacity reports use that same requirement:
with the default limit, seven or nine existing subscription DPS are allowed; ten are not. Full regular
qualification and mixed/other debug selections retain four-slot admission.
The conservative default is ten DPS instances across all regions. A run may
explicitly use an operator-confirmed limit for its selected subscription:
pass `--dps-capacity-limit 100` to the local controller, or set
`dps-capacity-limit` to `"100"` on the Integration Tests or Build and Publish
Release manual workflow. The confirmed 100-instance limit for subscription
`a386d5ea-ea90-441a-8263-d816368c84a1` does not apply to other subscriptions or
unconfigured runs; every workflow and local default remains ten. This input
does not change Azure quota, bypass inventory/ownership checks, or authorize
foreign-resource deletion. Values must be positive base-10 integers, not
booleans, fractions, empty strings or expressions.

The selected limit is recorded consistently in initial admission, fresh
pre-phase gates and cleanup capacity receipts. The independent workflow gate
receives the same trusted workflow input, rather than trusting receipt limits.
When evaluating local artifacts with `_evaluate_test_results.py`, supply
`--expected-dps-capacity-limit 100` explicitly for a run admitted with 100;
the default evaluator rejects such receipts. A raised limit does not make a
focused/debug run qualify as a full suite or change its required slot count.

Do not supply pinned shared resources. Caller data roles
use the existing DPS/Hub fixtures; native linking creates only its required
service-to-service roles. No first-party Graph/Device Update grant is added.

Regular runtime/cleanup budgets are 45/10 minutes; the full controller is bounded
at 140 minutes within the 150-minute CI service job. Cleanup is never skipped or
converted into a pass: policy, issuing CA, root CA, namespace, DPS, then Hub are
removed in dependency order with exact ownership receipts and final ARM absence
evidence. Before registration submission, persist the unique enrollment/device
and target intent plus an authoritative RegistryDevice baseline. Capture the
registration correlation before assertions, resolve `registryDeviceExternalId`
against the SDK's `properties.externalDeviceId`, and delete only the exact newly
owned RegistryDevice ARM ID before namespace/CA cleanup. External IDs are never
used as ARM names. Registration/enrollment records are removed only after this
descendant cleanup. If an operation ID is available, cleanup may read native
operation-status to resolve a partial response; it never resubmits registration.
If no authoritative external-ID mapping is available, or the match is ambiguous,
pre-existing or changed, cleanup fails explicitly and quarantines the namespace,
dedicated DPS/Hub and enrollment evidence for reconciliation. It never deletes
all enumerated devices or guesses a backend-generated ID. RegistryDevice DELETE
is submitted once through the declared SDK with resource-GET absence polling;
an uncertain delete is not replayed. Unexpected namespace children also fail
cleanup qualification.

Ambiguous ownership is a persistent conflict: later disappearance of one match
does not authorize deleting the survivor. Final DPS/Hub release requires both
RegistryDevice completion and, if the namespace was claimed, its exact completed
deletion receipt plus a fresh scoped ARM 404. CA or namespace cleanup failures
retain target references even after device cleanup succeeds. Controller cleanup
reports all failures and propagates the first original error rather than masking
it with a later release guard.

Integration tests end in "_int.py" so execute the following command to run all integration tests,
`pytest -k "_int.py"`

Execute the following command to run the IoT Hub integration tests:

`pytest azext_iot/tests/iothub/ -k "_int.py"`

To run specific test in any integration test file, such as:

`pytest azext_iot/tests/central/test_iot_central_int.py::TestIotCentral::test_central_query_methods_run`

#### Azure Resource Setup

The following resources will be needed for the integration tests.

- IoT Hub
- IoT Device Provisioning Service
- Azure Digital Twins instance
- IoT Central App
- Storage Account (with an empty Container)
- Event Grid Topic
- Event Hub Namespace with an Event Hub
- Service Bus Namespace with a Topic
- Azure Data Explorer Cluster with a Database

If specified in the pytest.ini configuration file, those resources will be used. Please ensure that the resources are in a clean, new state (ex: Iot Hub should not have any devices). Otherwise, new resources will be generated during the test startup and deleted during the test teardown.

> Note: If you interrupt test execution (for example via ctrl + C), the teardown or clean up processes may not run leaving resources in an indeterminant state.

#### Integration Test Environment Variables

You can either manually set the environment variables or use the `pytest.ini.example` file in the root of the extension repo. To use that file, rename it to `pytest.ini`, open it and set the variables as indicated below.

```
    AZURE_TEST_RUN_LIVE=True
    azext_iot_testrg=
    azext_iot_testhub=
    azext_iot_testdps=
    azext_iot_testdps_hub=
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

| Variable name 	| Tests Used for 	| Description 	|
|---------------	|----------------	|-------------	|
| `az_iot_testrg`  	|    All          	| The resource group that contains the IoT Hub and DPS instances or where all test resources are created. It will be the default resource group if any other resource group variables are not provided.	|
| `azext_iot_teststorageaccount`	| Iot Hub and Central Storage Tests	| The storage account used for running IoT Hub and Central storage tests. During these tests, your hub will be assigned a System-Assigned AAD identity, and will be granted the role of "Storage Blob Data Contributor" on the storage account you provide. Both the hub's identity and the RBAC role will be removed once the test completes. No role assignments are made for the IoT Central App.	|
| `azext_iot_teststoragecontainer`	| Iot Hub Storage Tests	| The name of blob container belonging to the `azext_iot_teststorageaccount` storage account. Defaults to 'devices' when not specified.	|
| `azext_iot_testhub` 	| Iot Hub Tests	| The name of the Iot Hub instance. 	|
| `azext_iot_testdps`	| Iot DPS Tests	| The name of the Iot DPS instance.	|
| `azext_iot_testdps_hub`	| Iot DPS Tests	| The name of the Iot Hub instance to use for DPS tests.	|
| `azext_iot_central_app_id`	| Iot Central Tests	| The IoT Central Application Id or name.	|
| `azext_iot_central_scope_id`	| Iot Central Tests	| The ID scope for the DPS associated with the IoT Central Application.	|
| `azext_iot_central_token`	| Iot Central Tests	| The api token to use for the IoT Central Application. This is only used to populate --token argument in IoT Central commands.	|
| `azext_iot_central_dns_suffix`	| Iot Central Tests	| The DNS Suffix to use for the IoT Central Application. This is only used to populate --central-dns-suffix argument in IoT Central commands.	|
| `azext_iot_central_primarykey`	| Iot Central Tests	| The IoT Central Application Id or name. Cannot be currently retrieved through the CLI.	|
| `azext_iot_central_storage_container`	| Iot Central Storage Tests	| The name of blob container belonging to the `azext_iot_teststorageaccount` storage account. Defaults to 'central' when not specified.	|
| `azext_dt_region`	| Digital Twin Tests	| The region to restrict Digital Twins creation. If not specified, will create the Digital Twins in a supported region.	|
| `azext_dt_adx_cluster`	| Digital Twin Data History Tests	| The name of the Azure Data Explorer Cluster to use. Azure Data Explorer Cluster creation time can take up to 20 minutes, so having a cluster is recommended.	|
| `azext_dt_adx_database`	| Digital Twin Data History Tests	| The name of the database in the Azure Data Explorer Cluster to use.	|
| `azext_dt_adx_rg`	| Digital Twin Data History Tests	| The resource group that contains the Azure Data Explorer Cluster. If not provided, `az_iot_testrg` will be used as the resource group. 	|
| `azext_dt_ep_eventgrid_topic`	| Digital Twin Endpoint Tests	| The Event Grid Topic to use.	|
| `azext_dt_ep_servicebus_namespace`	| Digital Twin Endpoint Tests	| The Service Bus Namespace to use.	|
| `azext_dt_ep_servicebus_policy`	| Digital Twin Endpoint Tests	| The policy for the topic in the Service Bus Namespace to use.	|
| `azext_dt_ep_servicebus_topic`	| Digital Twin Endpoint Tests	| The topic in the Service Bus Namespace to use.	|
| `azext_dt_ep_eventhub_namespace`	| Digital Twin Data History and Endpoint Tests	| The Event Hub Namespace to use.	|
| `azext_dt_ep_eventhub_policy`	| Digital Twin Endpoint Tests	| The policy for the Event Hub instance in the Event Hub Namespace to use.	|
| `azext_dt_ep_eventhub_topic`	| Digital Twin Data History and Endpoint Tests	| The Event Hub instance in the Event Hub Namespace to use.	|
| `azext_dt_ep_eventhub_topic_consumer_group`	| Digital Twin Data History Tests	| The Event Hub consumer group name to use. Defaults to "$Default".	|
| `azext_dt_ep_rg`	| Digital Twin Data History and Endpoint Tests	| The resource group that contains the endpoint (Event Hub, Event Grid, Service Bus) variables. If not provided, `az_iot_testrg` will be used as the resource group.	|
| `azext_dt_max_models_per_batch`	| Digital Twin Model Tests	| The maximum number of models per batch to submit to the DT Instance if the total set of models exceed the single page API limit. |
| `use_tags`	| IoT Hub, DPS, and Central Tagging	| Flag to enable resource tagging. Please see "Test Resource Tagging" for more details.	|
| `definition_id`	| IoT Hub, DPS, and Central Tagging	| Definition Id populated by an internal pipeline run. Can be manually set to customize the pipeline name tag. Please see "Test Resource Tagging" for more details.	|
| `job_display_name`	| IoT Hub, DPS, and Central Tagging	| Job Display Name populated by an internal pipeline run. Can be manually set to customize the pipeline name tag. Please see "Test Resource Tagging" for more details.	|
| `job_id`	| IoT Hub, DPS, and Central Tagging	| Job Id populated by an internal pipeline run. Can be manually set to customize the pipeline name tag. Please see "Test Resource Tagging" for more details.	|

### IoT Digital Twins

IoT Digital Twins test for creation of larger ontologies require ontology submodules to be cloned.

Run the following command to clone required submodules.

`git submodule update --init --recursive`

##### Test Resource Tagging

There are 4 more test variables used for tagging the test resources:
- `use_tags`
- `definition_id`
- `job_display_name`
- `job_id`

If `use_tags` is set to "True", then the resources created and used in Iot Central, DPS, and Hub tests will be tagged. The tested resources (IoT Hub, DPS, and Central App instances) will have two types of tags:
- number of test method runs (ex: `test_central_device_c2d_purge_success : 1` means that the test "test_central_device_c2d_purge_success" was run once)
- a pipeline name or id (ex: `pipeline_id : 00 Test IoT Central Python310 00000000-0000-0000-0000-000000000` generated from internal pipeline runs) which can be manually set with `definition_id`, `job_display_name` and `job_id`.

Other resources created for these tests (ex: Storage Accounts for IoT Hub and Central tests) will have tags showing which test resource is associated (ex: `iot_resource : test-app-xxx` shows that the tagged storage account was created to be tested with the IoT Central App `test-app-xxx`).

These are mainly used for test pipeline debugging and differentiating what resources were created for what runs.

#### Unit and Integration Tests Single Command

Execute the following command to run both Unit and Integration tests and output a code coverage report to the console and to a `.coverage` file.  You can configure code coverage with the `.coveragerc` file.

`pytest -v . --cov=azext_iot --cov-config .coveragerc`

#### Formatting and Linting

The repo uses the linter in `azdev`. For more information, see here: https://github.com/Azure/azure-cli-dev-tools#style-linter-check-and-testing

We use our flake8 and pylint rules. We recommend you set up your IDE as per the VSCode setup below for best compliance.

To manually run pylint with our rules, run this command:

```powershell
pylint azext_iot/ --rcfile=.pylintrc
```

To manually run flake8 with our rules, run this command:

```powershell
flake8 azext_iot/ --statistics --config=setup.cfg
```

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
