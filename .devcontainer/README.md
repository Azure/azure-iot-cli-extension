# Welcome to the Azure IoT CLI Extension codespace!

This codespace has everything you need to get started developing with Python and the Azure CLI.

Included VSCode Extensions:

- [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
- [Black Formatter](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter)
- [Python isort](https://marketplace.visualstudio.com/items?itemName=ms-python.isort)
- [VSCode Github Actions](https://marketplace.visualstudio.com/items?itemName=GitHub.vscode-github-actions)
- [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)

Included Azure CLI extensions:

- [azure-devops](https://github.com/Azure/azure-devops-cli-extension)

Additional software:

- **Azure CLI** (and a locally installed copy of this extension)

## Validate codespace setup:

<details>
<summary>
Validate local dev extension configuration
</summary>

- Ensure your local Python virtual environment is active:

  `az -v` should show you a local `Python location` path in your `env` folder:

  `/workspaces/azure-iot-cli-extension/env/bin/python`

- Ensure your development extension is added to the CLI:

  `az extension list -o table` should show your installed extensions.
  
  Look for the extension `azure-iot`, with `/workspaces/azure-iot-cli-extension` as the `Path` and `dev` as the `ExtensionType`

- Ensure you can lint and unit test your local code:

  `tox` will run these checks, more info in our [tox guide](../docs/tox-testing.md)

</details>

<details>
<summary>
Validate local dev environment
</summary>

- Ensure you can run commands from the extension:

  `az iot hub device-identity create -h` should display help text without asking you to install the extension

</details>

<details open>
<summary>Validate CLI login and Azure connection</summary>

- Login to azure CLI (choose one):

  1. Login with `az login --use-device-code`
  2. Open codespace in desktop: `Ctrl/Cmd + Shift + P > Codespaces: Open in VS Code Desktop` and run `az login`

- Ensure you have a valid subscription selected:

  `az account show -o table`

- List all IoT Hubs in your subscription:

  `az iot hub list -o table`

</details>