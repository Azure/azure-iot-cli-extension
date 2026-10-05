# Installation Troubleshooting Guide

## Compatibility

The current preview requires Azure CLI `2.73.0` or later, using Python `3.10` or
later. Use `az --version` to check both the CLI version and its Python runtime.
These requirements apply on Windows, Linux, and macOS.

## Problem

After installing Azure CLI in my supported Linux environment, I try to install the extension via `az extension add --name azure-iot` but I get an error that looks like:

```diff
- ImportError: libffi.so.5: cannot open shared object file: No such file or directory
```

## Solution

Make sure you install the right distribution of Azure CLI that is compatible with your platform.

For example using the recommended installation path of [Linux via apt](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-apt), validate that your `/etc/apt/sources.list.d/azure-cli.list` file has the proper distribution identifier.

On an Ubuntu 16.04 environment provided with the [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/install-win10) the sources list file should have an entry tagged with 'xenial':

`deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ xenial main`
