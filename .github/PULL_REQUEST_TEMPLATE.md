---
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

Thank you for contributing to the IoT extension!

This checklist is used to make sure that common guidelines for a pull request are followed.

### General Guidelines

- [ ] If introducing new functionality or modified behavior, are they backed by unit and integration tests?
- [ ] In the same context as above are command names and their parameter definitions accurate? Do help docs have sufficient content?
- [ ] Have **all** unit **and** integration tests passed locally? i.e. `pytest <project root> -vv`
- [ ] Have static checks passed using the .pylintrc and .flake8 rules? Look at the CI scripts for example usage.
