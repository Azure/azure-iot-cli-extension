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

### Azure Pipelines release automation

`.azure-devops/release.yml` is the manual release orchestrator. Keep its pipeline
definition on reviewed `dev`; `sourceBranch` independently selects `dev`,
`preview`, or `release/1.1.0-preview`. An optional full `sourceCommit` must be an
ancestor of that branch. The branch tip is otherwise resolved once. Every job
uses that same source commit, while receipts also record the separate automation
commit. Selected source branches must first receive the pipeline 147 migration
(including `releaseBuildId`), `scripts/select-openssl.sh`, and the existing
`scripts/check_index_compatibility.py`.

| Mode | Behavior |
| --- | --- |
| `Plan` (default) | Offline onboarding plan only. No Azure access, live tests, wheel, tag, release, or index PR. |
| `Validate` | Build and SBOM; full 12-way Python 3.10-3.13 / Ubuntu, Windows, Intel macOS unit and style matrix; security; command-table lint; required index compatibility; live pipeline 147 qualification. No publication. |
| `Release` | The same mandatory gates, then public GitHub release and an index PR. Automation must run from upstream `dev`. |

There is no skip-integration, continue-on-error, or manual GitHub `production`
approval step in this path. Failed, canceled, partially successful and skipped
dependencies cannot qualify publication. Index compatibility retains upstream's
MEDIUM-warning policy, but HIGH findings, tool failures and incomplete checks are
blocking. MSDO replaces the existing GitHub security task, not a separate
organization-mandated secret-scanning control.

**Operator setup (not performed by the YAML):**

1. Create the ADO definition with this YAML. During StartRight onboarding, keep
   any definition temporarily pointing at unrelated YAML disabled; correct the
   branch/path before running. Use `Plan` for the first run. `Validate` is a real,
   resource-creating integration run, not a dry run.
2. Configure non-queue-overridable `ReleaseAzureServiceConnection` and
   `ReleasePipFeedUrl` pipeline variables. The former names an approved ADO Azure
   service connection, preferably workload-identity federation. Its principal
   must read the **same corporate package feed** used by the existing release.
   The latter is that feed's HTTPS URL without credentials (`/simple/` is
   normalized). The build obtains an ARM-audience token inside `AzureCLI@2`,
   passes authenticated pip configuration only to build/SBOM child processes,
   and never emits the token or persists it in an artifact. Do not enable
   credential/debug tracing. Feed access is separate from integration-resource
   access; do not assume the existing test identity has it.
3. Set `ReleasePipelineId` in pipeline 147's `aziotcli_test_primary` group to this
   new definition's numeric ID. Grant the project Build Service **Queue builds**,
   **View builds**, **View build pipeline** and **Stop builds** on 147 as needed;
   grant 147 read access to the producer build/artifacts. Restrict permissions to
   these pipelines. Same-project orchestration uses `System.AccessToken`, not an
   ADO PAT. Do not hold a parent exclusive lock while waiting for a child that
   needs that lock.
4. Create the protected variable group `aziotcli_release_publish`, authorized
   only for the reviewed release definition. Set secret `ReleaseGitHubToken`
   to an organization-approved automation credential and `IndexForkRepository`
   to its existing `owner/azure-cli-extensions` fork. Grant only the necessary
   upstream IoT **Contents write**, fork **Contents write**, and index
   **Pull requests write** access. The GitHub checkout connection alone does not
   provide these capabilities. Credential policy, renewal, and expiry must cover
   publication after the potentially long qualification; this YAML does not
   mint or renew GitHub App tokens. Never provision a personal token as a
   shortcut around organizational policy.
5. Apply ADO branch-control checks on the publishing group and protect `dev` and
   all allowed source branches. Restrict editing/queuing the release definition
   and changing its variables, service connections, and group authorization.
   Script conditions are defense in depth, not a security boundary against
   someone who can edit pipeline YAML. Feature-branch development uses `Plan` or
   `Validate` **without publishing-group authorization**.
6. Install/authorize the Microsoft Security DevOps ADO extension and approve the
   agent pools. Hosted integration waiting needs a job entitlement covering the
   configured six-hour budget; otherwise select an approved pool with sufficient
   runtime. This ordinary YAML is **not a verified OneBranch/1ES governed
   template**. Obtain the applicable production classification, required template,
   security controls and service-connection approvals before production use.
   Mandatory organizational approvals are not bypassed.

The release builds exactly one `release-candidate` artifact containing a wheel,
`candidate.json`, and `SBOM.zip`. The SBOM retains runtime-only dependency
collection and the Windows-specific IoT device dependency; the SBOM executable
is version- and SHA-256-pinned. Pipeline 147 receives `releaseBuildId`, validates
the trusted producer/source/digest, and installs the same wheel rather than
rebuilding it. The parent requests all DPS/Hub/ADR/ADU services on Python 3.10
and 3.13, public ARM, `australiaeast`, requires the child to succeed, and verifies
the retained child candidate artifact.

Retain producer and child artifacts through qualification/recovery. A retried
integration waiter looks for the uniquely owned child; it will not blindly
queue another cohort. A failed child must be recovered through 147's existing
recovery procedure, or a new release run started after cleanup/admission checks.
Cancellation requests target only that release's child. Agent loss or an
uncertain queue response can still require operator inspection: check pipeline
147 and cleanup ownership before starting another run. Do not rebuild or replace
an already-published candidate artifact within the same release run.

Publication first stages a draft, verifies both uploaded asset digests, pins
`v<normalized wheel version>` to the qualified source commit, then makes the
release public automatically. Pre-release wheel versions set GitHub's prerelease
flag. Existing mismatched tags/assets are never moved or overwritten. An
identical public release is reused. **Public release already distributes the
wheel**; index-team approval only gates its addition to the CLI index.

After publication, the official `azdev extension update-index <wheel URL>` tool
appends the candidate without removing prior versions. The helper verifies the
version/URL/hash and that no other index entries changed, writes only the
approved fork, and creates or reuses the version-specific PR against
`Azure/azure-cli-extensions:main`. It never merges or approves that PR. A failure
here leaves the GitHub release public: retry the index stage, not a rebuild or
replacement release. Conflicting existing index branches require manual review.

This pipeline is additive: it does not disable existing GitHub workflows,
change schedules, or remove FICs. Cut those consumers over only after an
authorized end-to-end ADO validation and release rehearsal.

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
