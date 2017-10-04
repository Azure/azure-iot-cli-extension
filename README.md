# Microsoft Azure IoT CLI Extension for Windows and Linux

![Python](https://img.shields.io/pypi/pyversions/azure-cli.svg?maxAge=2592000)

This project provides new and exciting IoT commands and capabilities that do not exist in the vanilla Azure CLI. Functionality is provided as an Az CLI extension package.

Checkout the prebuilt package distributed on [Pypi](https://pypi.python.org/pypi/azure-cli-iot-ext).

# Features

- New device message send (device-to-cloud) supporting **amqp, mqtt and http** protocols
- Hub message send (cloud-to-device)
- Device twin operations
- Invoke device method
- Device simulation
- Generate SAS token


# Installation

This extension depends on Az CLI and will supplement existing IoT commands. **Even** if you have Az CLI installed make sure it is up to date and **supports** the `az extension` feature!

### Azure CLI

First follow the installation instructions on [GitHub](https://github.com/Azure/azure-cli) or [Microsoft Docs](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest) to setup Python and the Azure CLI in your environment.

### OS environment dependencies

Next depending on your OS environment you will need to install required C++ and Python shared libraries. These requirements come from the Azure [Python IoT SDK](https://github.com/Azure/azure-iot-sdk-python).

#### Windows
- Install the Visual [C++ VS 15 redistributable](https://www.microsoft.com/en-us/download/details.aspx?id=48145)

#### Linux
- The IoT SDK should work for Ubuntu Trusty and Xenial. 
- Ensure you have the following dependencies installed.
    - libboost1.54-all-dev ([trusty universe](https://packages.ubuntu.com/search?keywords=libboost1.54-all-dev&searchon=names&suite=all&section=all))
    - libpython2.7 for Python 2.7 or libpython3.4 for Python 3.4+ ([trusty](https://packages.ubuntu.com/search?suite=all&section=all&arch=any&keywords=libpython3.4&searchon=names))
    - libcurl4-openssl-dev

    **Notes**: 
        
    It is recommended to use package managers like apt-get or aptitude to install dependencies. 
    
    Read [this resource](https://digimaun.github.io/cloudsauce/2017/09/25/ubuntu-xenial-leveraging-trusty-packages/) to learn how to use trusty packages in xenial, with a specific example using libboost1.54-all-dev.
    

For more information on these dependencies refer to the [Python IoT SDK](https://github.com/Azure/azure-iot-sdk-python/blob/master/doc/python-devbox-setup.md#install-the-python-modules-using-pypi-wheels-from-pypi) project which is the major provider for this extension.

### Add extension to Az CLI 
Now that your environment has fulfilled prereqs you can leverage the Az CLI **extension add** capability. You will need to point the **--source** parameter of the add command to the IoT extension wheel package, either locally or a target URI.

```
az extension add --source <filepath.whl OR uri for .whl>
```

The easiest way to add the extension is to use the official [Pypi](https://pypi.python.org/pypi/azure-cli-iot-ext) distributed package, but you can also create a package locally from source.

To build the wheel locally, ensure you have the `wheel` package installed i.e. `pip install wheel`. Then run `python setup.py bdist_wheel` where the current directory is the extension root.

The az extension add command will download and install any additional Python dependencies required and may take a couple minutes to complete.

After the command finishes, the `az iot <subcommand>` collection should have new and overriden commands available for use.


# Command Guide

This is the current set of new commands. There is an assortment of parameters for each command! Make sure you add --help for detailed help information on either commands or parameters.

```python
az iot device twin show
az iot device twin update
az iot device message send
az iot hub message send
az iot device simulate
az iot device method
az iot device sas
```

## Developer setup

Extension development depends on a local Az CLI dev environment. First follow the [instructions](https://github.com/Azure/azure-cli/blob/master/doc/configuring_your_machine.md) for preparing your machine.

Next install the required C++ dependencies outlined in the user installation instructions.

Then update your `AZURE_EXTENSION_DIR` environment variable to a target extension deployment directory.

Example `export AZURE_EXTENSION_DIR=~/.azure/devcliextensions`

When you are ready to try extension changes in Az CLI

`pip install -U --target <extension deployment directory>/<extension name> <iot extension root>`

Repeat the above command as needed.


[Reference](https://github.com/Azure/azure-cli/tree/master/doc/extensions) docs for Az CLI Extension development

### Running Tests

Current testing patterns leverage [unittest](https://docs.python.org/3.6/library/unittest.html) and [coverage](https://coverage.readthedocs.io/en/coverage-4.4.1/).

Ensure you have **activated** your Python virtual environment for Az CLI.

**Unit tests:**

`python <extension root>/azext_iot/tests/test_iot_sdk_ext_unit.py`

**Integration tests:** 

Update the following environment variables prior to running integration tests.

`iot_ext_hub_connstring`, `iot_ext_hub_name`, `iot_ext_device_connstring`, `iot_ext_device_name`

`python <extension root>/azext_iot/tests/test_iot_sdk_ext_int.py`



## Known Issues

- Device feedback has a variable event trigger time.
- Device feedback may have issues with Py3 installations.
- iot device message send will take user_id as input but will be inserted.
in the message property bag rather than message meta data (until SDK updates).
- Chatty provider function output may still leak to std out.


## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.