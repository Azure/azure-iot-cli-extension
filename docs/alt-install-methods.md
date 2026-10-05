# Alternative Installation Methods

## From Extension Index method

Install the extension from the official Microsoft Azure CLI Extension Index

`az extension add --name azure-iot`

### Tips

- You can use `az extension list-available` to see all available extensions on the index
- It is possible to update an extension in place using `az extension update --name <extension name>`

## From whl package (remote or local) method

> This installation method is recommended for pinning to a specific version of a release.

Navigate to the project's [releases in GitHub](https://github.com/Azure/azure-iot-cli-extension/releases) to see the list of releases. Run the extension add command using the `--source` parameter.

The argument for the source parameter is either the URL path of the released extension package (ends with `.whl`) or the local path to the downloaded release package.

`az extension add --source <local file path to release.whl OR url for release.whl> --upgrade`

For example, replace `X.Y.Z` with the version of a published release:

```bash
az extension add --source 'https://github.com/Azure/azure-iot-cli-extension/releases/download/vX.Y.Z/azure_iot-X.Y.Z-py3-none-any.whl' --upgrade
```

## From local source method

You can create a wheel package locally from source to be used in Azure CLI.

To build the wheel locally, ensure you have the Python `wheel` package installed i.e. `pip install wheel`. Then run `python -m build` where the current directory is the extension root. The wheel (with .whl suffix) will be generated and available in the `dist` folder.

Then, follow the local package installation method.
