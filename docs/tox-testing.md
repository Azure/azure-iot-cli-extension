# Tox Testing Guide

[Tox](https://tox.wiki/) is a CLI tool used to run various python testing environments with specific dependencies.

Currently, our testing matrix is broken up into the following groups:

- Python versions to run tests:
    - 3.10
    - 3.11
    - 3.12
    - 3.13
- Azure CLI Core versions to test extension against:
    - `azmin` installs the minimum supported CLI version (currently `2.46.0`)
    - `azcur` installs the latest released CLI version from PyPi
    - `azdev` installs the CLI from your local CLI instance (located at `../azure-cli`)
- Types of tests to run:
    - Linting / style only
    - Unit tests
    - Integration tests


## Running Tox Locally
In order to run tox testing environments as currently configured, you must install tox (currently in `dev_requirements`, so already part of dev setup) and have the azure-cli repo cloned alongside your extension repo:

    ./azure-cli
    ./azure-iot-cli-extension

Environment strings can be passed to tox with `-e "env"` for a single environment, or `-e "env1, env2"` for multiple environments.

If you need to add additional inputs to `pytest` - you can do so by using `--` as a separator, like below (only test last failed, very verbose):

        `tox -e "python-azdev-unit" -- --lf --vv`

The first time you run a new environment in tox, it will perform some setup tasks and dependency installation which will incur some overhead, but ensuing test runs will be able to skip this step.

- Tox can detect dependency / command changes in tox.ini and other related settings, but does not check files external to tox (code, dev_requirements, etc).

- In order to rebuild a tox environment, you need to run tox with the `-r` switch.

The [current tox config](../tox.ini) supports local test configurations for the following environments:

- Linting
  - To run flake8 and pylint locally on your code, simply run:

        tox -e lint

- Various Python and AZ CLI Versions
  - The tox environment string (passed to `-e`) will be parsed as such:

        py{thon,3.10...3.13}-az{min,cur,dev}-{int,unit}

    |Python version | CLI version   | Test type     |
    |---------------|---------------|---------------|
    |"python"|"azmin"|"int"|
    |"py3.10"|"azdev"|"unit"|
    |"py3.11"|||
    |"py3.12"|||
    |"py3.13"|||

**If you choose not to select a specific python version (which is also the current default), you can use `python` instead, to invoke whichever interpreter version `python` invokes in your environment.**



### Tox Environment Selection Examples:

    tox -e "lint, python-azdev-unit"
        - Default if you run `tox` with no arguments
        - Run linters, current python/dev CLI unit tests
    tox -e "python-azcur-unit"
        - Current python interpreter, released azure CLI install, unit tests
    tox -e "py3.10-azmin-unit"
        - Python 3.10, min supported CLI, unit tests
    tox -e "py{3.10,3.13}-az{min,cur}-unit"
        - Python 3.10, min supported CLI core, unit tests
        - Python 3.10, currently released CLI core, unit tests
        - Python 3.13, max supported CLI core, unit tests
        - Python 3.13, currently released CLI core, unit tests


In order to list all recognized environments, you can type `tox -av`, which will display them all in a list:

![image](https://user-images.githubusercontent.com/13545962/217683727-1ec36d2c-e055-4677-a5a9-8f87cdcc987b.png)

## Integration workflow topology

`int_test.yml` runs a direct service × Python × region matrix after setup and unit
tests succeed. Every selected combination, including ADU, is independently eligible
to run, with `fail-fast: false`, no parallelism cap and no workflow/job concurrency
lock. Job names and result/coverage artifacts identify the service, Python and region.
The result gate checks the complete selected matrix independently of coverage reporting.

Owned Hub/DPS controllers still sequence their internal phases; ADR still uses
serial pytest. Controllers do not reserve slots or enforce subscription quota
admission. Inventory and exact-ID reads still establish ownership, detect
collisions, reconcile known resources and verify cleanup; they are not quota
count gates. Azure provisioning errors, including quota rejections, fail the run.
The existing canary scope, identities/RBAC, quarantine and ownership checks still apply.
Overlapping runs and additional Python/region combinations can consume resources
concurrently; the former bounded-cohort reservation does not apply.

Every selected service runs its full branch-specific suite. GitHub dispatch and
reusable workflows have no ADR pytest filter, certificate-revocation opt-in or DPS
capacity-limit input; the release caller does not supply a quota override either.
Both ADR Microsoft CA revocation cases run using newly created, test-owned CAs.
Pre-existing resources are rejected before creation, and the certificate action
tracker independently enforces exact ownership before any mutation.
Unrelated optional external/preprovisioned fixtures retain their safety controls:
selecting the full suite never authorizes mutation of external credentials.
Local focused-debug controls remain available and cannot qualify a full suite.

## ADR live-test budgets

The GitHub ADR service job reserves **360 minutes**, including setup and reporting.
The root integration matrix applies this budget directly to each ADR service job.
The job ceiling does not extend per-operation provisioning waits.

ADR runs serially. Its SU-link case already allows 175 minutes for provisioning,
native link recovery and cleanup, followed later by a separate 75-minute SU-instance
lifecycle. Other ordinary cases retain their 15-minute cap. Two completed-job logs showed
the latter lifecycle starting about 109 minutes into a former 120-minute job:
SU-link alone consumed 56–63 minutes. Preserving its full existing envelope plus
the observed other work and reporting margin required about 342 minutes before
the owned Hub/DPS fixture alignment below.

Owned no-wait Hub/DPS link fixtures use the native CLI's **600-second** readiness
default. A local run exhausted the former 240-second bound while an accepted
recovery was still in progress, not after a terminal service rejection. The same
monotonic deadline covers the initial snapshot, calls, backoff and polling;
accepted work is not replayed and invalid-request failures remain non-retryable.
The three-add lifecycle reserves **45 minutes** (15 minutes plus three 10-minute
windows), without increasing native CLI or SU provisioning defaults. This adds
18 minutes to its former allowance and puts that observed-prefix extrapolation
at about 360 minutes.

360 minutes is practical headroom, **not a guarantee of full coverage or success**.
All case maxima combined exceed one hosted job. A cancellation must be reported
as incomplete, with failures/skips and unstarted cases preserved; backend failures
must not be skipped, suppressed, or converted to successful coverage.

`ADR-int` writes `test-result/integration-outcomes.json` and `failures.txt` after
collection, each case start and each setup/call/teardown report. These files are
atomically replaced and flushed before returning from the hook, so a killed job
retains failed, active/incomplete and unstarted cases without requiring pytest's
final summary or JUnit shutdown. `session_finished: false` is not a passing run.
Skips remain explicitly skipped, not passed coverage. The GitHub always-run result
step preserves these files rather than replacing them with a final-summary scrape.

The opt-in `--integration-results-dir` is for serial pytest (`-n 0`) only and does
not change other services' reporting. Receipts include only code addresses,
per-selection case numbers, phase/outcome enums and numeric durations: parameter
values, errors, captured logs and skip reasons are never persisted. Repeated
parameter cases have distinct numbers even when their sanitized addresses match.
These are test-execution receipts, **not proof that Azure resources were cleaned up**.
