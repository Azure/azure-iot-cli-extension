# Integration Test Performance and Stability Plan

Scope: changes only to test code and config (`azext_iot/tests/**`, `tox.ini`, `.github/workflows/int_test.yml`). Command logic and assertions are not changed.
Baseline: runs 36647140680 and 36543696449 (australiaeast, py3.13). Subscription quota is out of scope.

## Summary

| Service | Today | Target | Main lever |
|---|---|---|---|
| ADR | 213–234 min, plus reruns | 60–70 min | Balanced parallel workers; fix 3 flaky backend paths |
| HubControl | 205 min | 60–75 min | Shard into jobs; delete without waiting; create dependencies in parallel |
| ADU | 128–141 min | 68–77 min | Split `test_adu_instance_int.py` |
| HubData | 110 min | 30–40 min | Run the SAS phase as its own job; shard the regular phase |
| DPS | 53 min | 25–30 min | Run the 3 phases as parallel jobs |

Longest job goes from about 3.9 h to about 75 min. ADR flakes currently force whole-suite reruns: run 36647140680 needed 4 ADR attempts, each 3.5 h or more.

## ADR

Performance:
- [ ] Enable xdist with balanced groups (4–5 workers), longest tests first. Plain `loadgroup` does not order by duration and only reaches about 90–99 min.
- [ ] Put `test_adr_link_su_delete` (53 min) and `test_adr_link_hub_dps_delete` (23 min) in different groups; they are in the same file today.
- [ ] Give each worker its own Azure CLI config dir, because the preflight runs `account set`.
- [ ] Keep the existing polling intervals (already 10 s) and the Software Update PUT sequences (limited by the service).

Stability (backend issues, 2026-09-30 attempt 3):
- [ ] **CA additional-policy rejection** (`test_adr_certificate_authority_lifecycle`). The backend returns `AsyncOperationFailed: Parent certificate authority '<guid>' already has an active certificate policy.`, and `is_expected_policy_rejection` (`_certificate_fixtures.py:25-67`) does not match it. Accept this exact message pattern (GUID anchored) as positive evidence. Do not retry this call; the rejection is deterministic. Backend ask: a stable, policy-specific error code.
- [ ] **Hub-link identity rotation, IH400913** (`test_adr_link_int.py` Step 7, around line 601). The system-assigned identity was denied about 6 s after its role grant. Add a bounded retry for this operation only:
  - Retry only on `IdentityRotationUpdateFailed` / IH400913 authorization denial.
  - Before each retry, wait until the link reaches a terminal state and confirm the identity and target are unchanged.
  - Back off 30/60/120 s, rerun the same `link hub update`, and keep the identity-mismatch guard and final assertions.
- [ ] **DPS link denied namespace read, IH400315** (Step 1, `link_dps_with_readiness`). ADR returns the generic "DPS resource rejected the link request as invalid". Extend the retry classifier in `_readiness.py` (`_authorization_failure`, around line 272) to accept this generic `LinkInitiateFailed` for DPS only when grants were just created. Recover with the existing identity-preserving update, with the same 30/60/120 s backoff and time budget. Never repeat `link add` blindly.
- [ ] No blanket pytest reruns: they recreate resources and new role assignments, which reproduces the same race.

## HubControl

- [ ] Split the suite into 3–5 jobs, each owning its resources and receipts, and keep `-n 0` inside each job:
  - state: split in 2
  - message_endpoint + route: split in 2
  - core, certificate and tls13 tests
- [ ] Module teardown: delete Cosmos, Event Hubs, Service Bus, storage and Hubs with `--no-wait`. Resources are already recorded (`_hub_ownership.py:619`), and `_hub_phase_runner.cleanup_regular` waits until they are gone. Saves up to about 30 min.
- [ ] Create each module's dependencies in parallel using subprocesses or separate CLI instances, not threads on the shared `EmbeddedCLI`.

## ADU

- [ ] Split `test_adu_instance_int.py` into 2 files (or use `xdist_group` + `--dist=loadgroup`). Its two tests (73 and 67 min) currently run back to back on one worker.
- [ ] Keep the synchronous instance-delete assertion. Fixture hub deletes may skip waiting only if a later completion check replaces the wait.

## HubData

- [ ] Run the regular (Entra) and SAS phases as separate matrix jobs, with separate receipts and output/coverage paths. This alone brings the job to about 85 min.
- [ ] Split the regular phase into 2–3 serial groups, each owning its Hubs. Setup includes role assignments, data loading and readiness checks, not only Hub creation.
- [ ] Monitor-events tests: also stop once the expected message count arrives, but keep the timeout-path cases. Saves about 2–3 min.

## DPS

- [ ] Run the regular, service-SAS and local-auth-toggle phases as parallel matrix jobs; resources are already separated per phase (`dps/conftest.py:223`). The job becomes about 28–31 min.
- [ ] Replace the fixed `sleep(60)` calls (`dps/conftest.py:157`, `:476`) with readiness polling. The Hub-link sleep must still confirm the DPS identity's role has taken effect.
- [ ] Optional: create the CSR-issuance chain (`dps/_csr_issuance.py:347`) in parallel with the phase's Hub and DPS.

## Validation

- [ ] Update the workflow and parser unit tests (`test_workflow_*_unit.py`, `test_command_loader_unit.py` if the CLI surface is touched).
- [ ] Two live runs per service to compare against the baseline timings.
