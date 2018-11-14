## Alternative Installation Methods

### Index Method

Install the extension from the official Microsoft Azure CLI Extension Index

`az extension add --name azure-cli-iot-ext`

**Tips**

- You can use `az extension list-available` to see all available extensions on the index
- It is possible to update an extension in place using `az extension update --name <extension name>`


### URL or Local Package Method

Navigate to this project's release tab in GitHub to see the list of releases. Run the extension add command using the `--source` parameter.

The argument for the source parameter is either the URL download path (the extension package ends with '.whl') of your chosen release, or the local path to the extension where you downloaded the release package.

`az extension add --source <local file path to release.whl OR  url for release.whl>`

For example, to install version 0.3.2

`az extension add --source 'https://github.com/Azure/azure-iot-cli-extension/releases/download/v0.3.2/azure_cli_iot_ext-0.3.2-py2.py3-none-any.whl'`

### Source Package Method

You can create a wheel package locally from source to be used in Azure CLI.

To build the wheel locally, ensure you have the Python `wheel` package installed i.e. `pip install wheel`. Then run `python setup.py bdist_wheel` where the current directory is the extension root. The wheel (with .whl suffix) will be generated and available in the new `dist` folder.

Then, follow the local package installation method.