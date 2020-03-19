# Installation Troubleshooting Guide

## Compatibility

Before installation ensure that your Azure CLI version meets the following criteria. The criteria differs based on OS and method of installation. Use `az --version` to determine the CLI version.

In all cases your CLI needs to be at least `v2.0.70`.

| CLI Install Method  | NOT compatible with |
| ------------- | ------------- |
| Windows via MSI  | v2.0.34 to v2.0.38  |
| Windows via PIP, Linux or macOS  | v2.0.34 to v2.0.36  |

## Problem

After installing Azure CLI in my supported Linux environment, I try to install the extension via `az extension add --name azure-iot` but I get an error that looks like:

```diff
- ImportError: libffi.so.5: cannot open shared object file: No such file or directory
```

## Solution

Make sure you install the right distribution of Azure CLI that is compatible with your platform.

For example using the recommended installation path of [Linux via apt](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli-apt?view=azure-cli-latest), validate that your `/etc/apt/sources.list.d/azure-cli.list` file has the proper distribution identifier.

On an Ubuntu 16.04 environment provided with the [Windows Subsystem for Linux](https://docs.microsoft.com/en-us/windows/wsl/install-win10) the sources list file should have an entry tagged with 'xenial':

`deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ xenial main`
