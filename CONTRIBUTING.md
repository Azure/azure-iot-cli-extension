# Contributing

## Dev Setup

1. Get Python 3: https://www.python.org/downloads/

#### Required Repositories

You must fork and clone the repositories below. Follow the videos and instructions found [here](https://github.com/Azure/azure-cli-dev-tools#setting-up-your-development-environment).

1. https://github.com/Azure/azure-cli

2. https://github.com/Azure/azure-iot-cli-extension

> IMPORTANT: When cloning the repositories and environments, ensure they are all siblings to each other. This makes things much easier down the line.

```
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

It is recommended that you set the following environment variables in a way such that they are persisted through machine restarts.

You can run this setup in `bash` or `cmd` environments, this documentation just show the `powershell` flavor.

1. Create a directory for your development extensions to live in

    ```powershell
    mkdir path/to/source/extensions/azure-iot
    ```

2. Set `AZURE_EXTENSION_DIR` to the following

    ```powershell
    $env:AZURE_EXTENSION_DIR="path/to/source/extensions"
    ```

3. Set `PYTHONPATH` to the following. Order matters here so be careful.

    ```powershell
    $env:PYTHONPATH="path/to/source/azure-iot-cli-extension;path/to/source/extensions/azure-iot"
    ```

Restart any PowerShell windows you may have open and reactivate your python environment. Check that the environment variables created above have persisted.

#### azdev Steps

Similar to the video, just execute the following command.

```powershell
azdev setup -c path/to/source/azure-cli
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

#### Unit Tests

You may need to install the dev_requirements for this

```powershell
pip install -r path/to/source/dev_requirements
```

_Hub:_  
`pytest azext_iot/tests/test_iot_ext_unit.py`

_DPS:_  
`pytest azext_iot/tests/test_iot_dps_unit.py`

#### Integration Tests

Integration tests are run against Azure resources and depend on environment variables.

##### Azure Resource Setup

1. Create IoT Hub

    > IMPORTANT: Your IoT Hub must be created specifically for integration tests and must not contain any devices when the tests are run.

2. Create Files Storage - In IoT Hub, click Files, create a new Storage Account and link to an empty Container.

3. Create IoT Hub Device Provisioning Service (DPS)

4. Link IoT Hub to DPS - From DPS, click "Linked IoT Hub" and link the IoT Hub you just created.

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

Execute the following command to run both Unit and Integration tests and output a code coverage report to the console and to a `.coverage` file.  You can configure code coverage with the `.coveragerc` file.

`pytest -v . --cov=azext_iot --cov-config .coveragerc`

#### Formatting and Linting

We use our flake8 and pylint rules. We recommend you set up your IDE as per the VSCode setup below for best compliance.

We are also starting to use `python black`. To set this up on VSCode, see the following blog post

https://medium.com/@marcobelo/setting-up-python-black-on-visual-studio-code-5318eba4cd00

## Optional

#### VSCode setup

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
    ```
    "args": [
        "--a", "value", "--b", "value"
    ],
    ```

    Incorrect: 
    ```
    "args": [
        "--a value --b value"
    ],
    ```

5. Set up python black.

6. You should now be able to place breakpoints in VSCode and see execution halt as the code hits them.

### Python debugging

https://docs.python.org/3/library/pdb.html


1. `pip install pdb`
2. If you need a breakpoint, put `import pdb; pdb.set_trace()` in your code
3. Run your command, it should break execution wherever you put the breakpoint.

# Microsoft CLA

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.
