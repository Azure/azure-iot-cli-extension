# Installation Troubleshooting Guide

## Compatibility

The `1.0.0b2` preview requires Azure CLI `2.73.0` or later, using Python `3.10`
or later. Use `az --version` to check both the CLI version and its Python runtime.
These requirements apply on Windows, Linux, and macOS.

If the installed extension is older than expected, check it with
`az extension show --name azure-iot --query version --output tsv`. Name-based
installation only selects versions in the extension index. For a preview that is
not yet indexed, follow the [wheel installation instructions](alt-install-methods.md).

## Historical Linux installation issue

The example below describes an older Ubuntu 16.04 installation, not a recommended
platform for this preview. Use the current
[Azure CLI installation instructions](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
for supported platforms.

### Problem

After installing Azure CLI in my supported Linux environment, I try to install the extension via `az extension add --name azure-iot` but I get an error that looks like:

```diff
- ImportError: libffi.so.5: cannot open shared object file: No such file or directory
```

### Solution

Make sure you install the right distribution of Azure CLI that is compatible with your platform.

For example using the recommended installation path of [Linux via apt](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-apt), validate that your `/etc/apt/sources.list.d/azure-cli.list` file has the proper distribution identifier.

On an Ubuntu 16.04 environment provided with the [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/install-win10) the sources list file should have an entry tagged with 'xenial':

`deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ xenial main`
