---
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

Thank you for contributing to the IoT extension!

This checklist is used to make sure that common guidelines for a pull request are followed.

### General Guidelines

Intent for Production

- [ ] It is expected that pull requests made to default or core branches such as `dev` or `main` are of production grade. Corollary to this, any merged contributions to these branches may be deployed in a public release at any given time. By checking this box, you agree and commit to the expected production quality of code.

Basic expectations

- [ ] If introducing new functionality or modified behavior, are they backed by unit and/or integration tests?
- [ ] In the same context as above are command names and their parameter definitions accurate? Do help docs have sufficient content?
- [ ] Have **all** the relevant unit **and** integration tests pass? i.e. `pytest <project root> -vv`. Please provide evidence in the form of a screenshot showing a succesful run of tests locally OR a link to a test pipeline that has been run against the change-set.
- [ ] Have linter checks passed using the `.pylintrc` and `.flake8` rules? Look at the CI scripts for example usage.
- [ ] Have extraneous print or debug statements, commented out code-blocks or code-statements (if any) been removed from the surface area of changes?
- [ ] Have you made an entry in HISTORY.rst which concisely explains your user-facing feature or change?

Azure IoT CLI maintainers reserve the right to enforce any of the outlined expectations.

A PR is considered **ready for review** when all basic expectations have been met (or do not apply).
