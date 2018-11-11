# Contributing

## Development Machine Setup

1. Setup Azure CLI Development Environment

    - Follow the [Azure CLI: Setting up your development environment](https://github.com/Azure/azure-cli/blob/master/doc/configuring_your_machine.md) steps to setup your machine for general Azure CLI development.
    - Move on to the next step when you can successfully run `azdev` and see the help message.

1. Update AZURE_EXTENSION_DIR and PYTHONPATH Environment Variables

    By default, CLI extensions are installed to the `~/.azure/cliextensions` directory.  For extension development, you'll want to update the AZURE_EXTENSION_DIR environment variable to `~/.azure/devcliextensions`, so your development extensions don't collide with your production extensions.

    You will also need to add both the project root and and devcliextensions directory to PYTHONPATH.

    1. Navigate to the root of this repo on your local machine:

    ```
    cd << clone root >>
    ```

    1. Run the following script to set the environment variables.

    - Windows:  

    ```
    set EXTENSION_PATH=%USERPROFILE%\.azure\devcliextensions\
    mkdir %EXTENSION_PATH%
    setx AZURE_EXTENSION_DIR %EXTENSION_PATH%
    setx PYTHONPATH %PYTHONPATH%;%EXTENSION_PATH%azure-cli-iot-ext;%CD%
    ```
    - Linux: 

    ```
    export EXTENSION_PATH=~/.azure/devcliextensions/
    mkdir -p $EXTENSION_PATH
    echo $"export AZURE_EXTENSION_DIR=$EXTENSION_PATH" >> ~/.bash_profile
    echo $"export PYTHONPATH=$PYTHONPATH:${EXTENSION_PATH}azure-cli-iot-ext:$(pwd)" >> ~/.bash_profile
    ```

1. Install Extension

    1. Navigate to the root of this repo on your local machine:

    ```
    cd << clone root >>
    ```

    1. Install the Extension

    - Windows:
    ```
    pip install -U --target %AZURE_EXTENSION_DIR%/azure-cli-iot-ext .
    ```

    - Linux: 
    ```
    pip install -U --target $AZURE_EXTENSION_DIR/azure-cli-iot-ext .
    ```

1. Verify Setup

    Run the following command to view installed extensions:

    `az extension list`

    You should see the following output.

    ```json
    [
    {
        "extensionType": "whl",
        "name": "azure-cli-iot-ext",
        "version": "0.6.0"
    }
    ]
    ```

Please use `az --debug` if you run into any issues, or file an issue in this GitHub repo.

Please refer to the [Azure CLI Extension Guide](https://github.com/Azure/azure-cli/tree/master/doc/extensions) for further information and help developing extensions.

### Running Tests

1. Install Dependencies

    The tests make use of [pytest](https://docs.pytest.org/en/latest/) and [unittest](https://docs.python.org/3.6/library/unittest.html). We also use `pytest-mock` and `pytest-cov` plugins for pytest so make sure you `pip install` these dependencies beforehand. You can leverage our `dev_requirements` file at the root of this project to install from.

    Run the following to install of the Python dependencies for this extension:

    `pip install -r dev_requirements`

1. Activate Virtual Environment

    1. Navigate to the root of of your CLI extension project

    1. Create a new virtual environment “env” for Python in the root of your clone. You can do this by running:

        Windows:
        ```BatchFile
        python -m venv env
        ```
        OSX/Ubuntu (bash):
        ```Shell
        python -m venv env
        ```
    1. Activate the env virtual environment by running:

        Windows:
        ```BatchFile
        env\scripts\activate.bat
        ```
        OSX/Ubuntu (bash):
        ```Shell
        ./env/bin/activate
        ```

#### Unit tests

_Hub:_  
`pytest azext_iot/tests/test_iot_ext_unit.py`

_DPS:_  
`pytest <extension root>/azext_iot/tests/test_iot_dps_unit.py`

#### Integration tests

Currently integration tests leverage Azure CLI live scenario tests. Update the following environment variables OR use an updated pytest.ini (copying and renaming pytest.ini.example) in the extension root directory prior to running integration tests.

These variables are **shared** between Hub and DPS integration tests:

`AZURE_TEST_RUN_LIVE` # Set to 'True' to hit live endpoints.

`azext_iot_testrg` # Target resource group for tests.

`azext_iot_testhub` # Target IoT Hub for respective category of tests.

Now you can run **Hub** integration tests:

`pytest <extension root>/azext_iot/tests/test_iot_ext_int.py`

_Optionally_ set `azext_iot_teststorageuri` to your empty blob container sas uri to test device export and enable file upload test. For file upload, you will need to have configured your IoT Hub before running.

For **DPS** update the following environment variable prior to running.

`azext_iot_testdps` # Target IoT Hub DPS for respective category of tests.

Now you can run **DPS** integration tests:

`pytest <extension root>/azext_iot/tests/test_iot_dps_int.py`

#### All tests and coverage in one command

At this point if your environment has been setup to execute all tests, you can leverage pytest discovery to run all tests and provide a coverage report.

`pytest -v <extension root> --cov=azext_iot --cov-config <extension root>/.coveragerc`



This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.