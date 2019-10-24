# :exclamation: Breaking Announcements :exclamation:

**9/14/18**
In order to satisfy new CI linter rules for the Azure CLI, we have replaced multi-character short options (like '-props', or '-pri') with long option versions ('--props', '--pri').

The option names have not changed, but to fix any existing scripts, please use the '--' prefix for any command options that are not single characters. Single character options such as '-l', '-n', and '-d' are unaffected.

**6/21/18**
The Windows Installer for Azure CLI since version 2.0.34 has an issue with the packaged pip. This issue prevents the IoT extension from being installed.

To fix, upgrade using at least the 2.0.39 MSI.

The error looks like this:

```bash
Command '['C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\python.exe', '-m', 'pip', 'install', '--target', 'C:\Users\myuser\.azure\cliextensions\azure-cli-iot-ext', 'C:\Users\myuser\AppData\Local\Temp\tmpkds3dj8q\azure_cli_iot_ext-0.4.5-py2.py3-none-any.whl', '-vv', '--disable-pip-version-check', '--no-cache-dir']' returned non-zero exit status 2.
Pip failed
```

Look at this [issue thread](https://github.com/Azure/azure-iot-cli-extension/issues/33#issuecomment-399200521) for an alternative workaround.

___

Versions 2.0.34 to 2.0.36 of Azure CLI are **NOT** compatible with the IoT extension.

You will see an error that looks like this when running commands with multi-character short options:

`command authoring error: multi-character short option '-props' is not allowed. Use a single character or convert to a long-option.`

We recommend skipping these version. Please look at the [compatibility](./README.md#compatibility) section below for up to date guidelines.
