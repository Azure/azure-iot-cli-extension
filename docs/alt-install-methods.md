# Alternative Installation Methods

## From Extension Index method

Install the extension from the official Microsoft Azure CLI Extension Index

`az extension add --name azure-iot`

To install or update to an indexed preview, use:

```bash
az extension add --name azure-iot --allow-preview --upgrade
```

This command only selects versions available in the extension index. Publishing a
GitHub release does not automatically add that version to the index. For
`1.0.0b2`, use the wheel method below until its index entry is available.

### Tips

- You can use `az extension list-available` to see all available extensions on the index
- It is possible to update an extension in place using `az extension update --name <extension name>`

## From whl package (remote or local) method

> This installation method is recommended for pinning to a specific version of a release.

Navigate to the project's [releases in GitHub](https://github.com/Azure/azure-iot-cli-extension/releases) to see the list of releases. Run the extension add command using the `--source` parameter.

The argument for the source parameter is either the URL path of the released extension package (ends with `.whl`) or the local path to the downloaded release package.

`az extension add --source <local file path to release.whl OR url for release.whl> --upgrade`

For example, after the `1.0.0b2` GitHub release is published, install its wheel:

```bash
az extension add --source 'https://github.com/Azure/azure-iot-cli-extension/releases/download/v1.0.0b2/azure_iot-1.0.0b2-py3-none-any.whl' --upgrade
```

The public URL is not available while the release is a draft. To test a draft,
download its wheel using an account with access and pass the local file path to
`--source`. Use `az extension show --name azure-iot --query version --output tsv`
to confirm the installed version is `1.0.0b2`.

## From local source method

You can create a wheel package locally from source to be used in Azure CLI. Use
Python `3.10` or later and check out the branch or commit you intend to build.

From the extension root, install the build frontend and build the package:

```bash
python -m pip install build
python -m build
```

For this `1.0.0b2` source, install the generated wheel:

```bash
az extension add --source ./dist/azure_iot-1.0.0b2-py3-none-any.whl --upgrade
```
