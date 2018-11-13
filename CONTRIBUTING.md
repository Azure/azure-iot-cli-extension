# Contributing

## Development Machine Setup

1. Setup Azure CLI Development Environment

    - Follow the [Azure CLI: Setting up your development environment](https://github.com/Azure/azure-cli/blob/master/doc/configuring_your_machine.md) steps to setup your machine for general Azure CLI development.
    - Move on to the next step when you can successfully run `azdev` and see the help message.

    > Make sure you keep the virtual environment you created above activated while completing following steps.

1. Update AZURE_EXTENSION_DIR and PYTHONPATH Environment Variables

    By default, CLI extensions are installed to the `~/.azure/cliextensions` directory.  For extension development, you'll want to update the AZURE_EXTENSION_DIR environment variable to `~/.azure/devcliextensions`, so your development extensions don't collide with your production extensions.

    You will also need to add both the project root and and devcliextensions directory to PYTHONPATH.

    1. Navigate to the root of this repo on your local machine:

    ```
    cd << clone root >>
    ```

    1. Run the following script to set the environment variables.

    **Windows:**

    ```
    set EXTENSION_PATH=%USERPROFILE%\.azure\devcliextensions\
    mkdir %EXTENSION_PATH%
    set AZURE_EXTENSION_DIR=%EXTENSION_PATH%
    set PYTHONPATH=%PYTHONPATH%;%EXTENSION_PATH%azure-cli-iot-ext;%CD%
    ```
    **Linux:**

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

    **Windows:**
    ```
    pip install -U --target %AZURE_EXTENSION_DIR%/azure-cli-iot-ext .
    ```

    **Linux:**
    ```
    pip install -U --target $AZURE_EXTENSION_DIR/azure-cli-iot-ext .
    ```

1. Verify Setup

    Run the following command to view installed extensions:

    `az -debug`

    That will output which directory is being used to load extensions and it will show that the `azure-cli-iot-ext` extension has been loaded.

    ```
    Extensions directory: '...\.azure\devcliextensions\'
    Found 1 extensions: ['azure-cli-iot-ext']
    ```

Please use `az --debug` if you run into any issues, or file an issue in this GitHub repo.

Please refer to the [Azure CLI Extension Guide](https://github.com/Azure/azure-cli/tree/master/doc/extensions) for further information and help developing extensions.

### Running Tests

1. Install Dependencies

    This project utilizes the following: [pytest](https://docs.pytest.org/en/latest/), [unittest](https://docs.python.org/3.6/library/unittest.html), `pytest-mock`, and `pytest-cov`.

    Run the following to install them:

    `pip install -r dev_requirements`

1. Activate Virtual Environment

    Ensure that the virtual environment you created while setting up your machine for general Azure CLI development is activated and the dev_setup.py script has been run.

#### Unit Tests

_Hub:_  
`pytest azext_iot/tests/test_iot_ext_unit.py`

_DPS:_  
`pytest azext_iot/tests/test_iot_dps_unit.py`

#### Integration Tests

Integration tests are run against Azure resources and depend on environment variables.

##### Azure Resource Setup

1. Create IoT Hub
> IMPORTANT: Your IoT Hub must be created specifically for integration tests and must not contain any devices when the tests are run.
1. Create Files Storage - In IoT Hub, click Files, create a new Storage Account and link to an empty Container.
1. Create IoT Hub Device Provisioning Service (DPS)
1. Link IoT Hub to DPS - From DPS, click "Linked IoT Hub" and link the IoT Hub you just created.

##### Environment Variables
You can either manually set the environment variables or use the `pytest.ini.example` file in the root of the extension repo. To use that file, rename it to `pytest.ini`, open it and set the variables as indicated below.

```
    AZURE_TEST_RUN_LIVE=True
    azext_iot_testrg="Resource Group that contains your IoT Hub"
    azext_iot_testhub="IoT Hub Name"
    azext_iot_testhub_cs="IoT Hub Connection String"
    azext_iot_testdps="IoT Hub DPS Name"
    azext_iot_teststorageuri="Blob Container SAS Uri"
```

`azext_iot_teststorageuri` is optional and only required when you want to test device export and file upload functionality. You can generate a SAS Uri for your Blob container using the [Azure Storage Explorer](https://azure.microsoft.com/en-us/features/storage-explorer/).  You must also configure your IoT Hub's File Upload storage container via the Azure Portal for this test to pass.


##### IoT Hub

Execute the following command to run the IoT Hub integration tests:

`pytest azext_iot/tests/test_iot_ext_int.py`


##### Device Provisioning Service

Execute the following command to run the IoT Hub DPS integration tests:

`pytest azext_iot/tests/test_iot_dps_int.py`

#### Unit and Integration Tests Single Command

Execute the following command from the root of your extension to run both Unit and Integration tests and output a Code Coverage report to a `.coveragerc` file.

`pytest -v . --cov=azext_iot --cov-config .coveragerc`



#### Microsoft CLA

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.