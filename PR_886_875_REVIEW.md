# ADR workflow and radar release migration

## Scope

[Azure/azure-iot-cli-extension#886](https://github.com/Azure/azure-iot-cli-extension/pull/886) and
[Azure/azure-iot-cli-extension#875](https://github.com/Azure/azure-iot-cli-extension/pull/875)
are separate draft PRs rebased onto `release/1.1.0-preview`, starting at
`f303a8e3a798ab7c66f4510cf1f70c91201071a1`. Only each feature's delta was
transplanted; obsolete history from the deleted base was not replayed.
The release SDKs, version, Registry Device commands, and link recovery remain authoritative.

## Required compatibility adjustments

| Area | Adjustment |
| --- | --- |
| Service roles | Reuse the release role matrix, including the namespace SAMI's DPS provisioning role independently of outbound UAMI, and three Software Updates grants without the obsolete ADU first-party Graph grant. |
| Authorization | Missing grants require effective role-assignment write permission at the relevant scopes; do not restrict guidance to Owner/UAA role names. |
| Link completion | Radar waits in its worker through the release provider, preserving bounded propagation recovery and protection against replaying ambiguous writes. |
| Workflow exports | Use supported outbound identity flags and pin every generated command to the reviewed subscription. Resolve linked targets and identities in their resource-ID subscription without changing the selected namespace subscription. |
| Terminal lifecycle | Suppress provider Rich Live displays while radar is active, restore console state on exit, and reject overlapping setup including stale confirmation callbacks. |
| Compatibility tests | Preserve the release parser inventory and extend explicit live-test selection for the new workflow/radar cases. |

Strict reviews used **Claude Opus 5.5 with high reasoning effort**. Actionable findings
on command flags, subscription routing, and overlapping execution were repaired with
parser, scoped-client, and headless regression coverage. Matching-link RBAC repair is
also marked as a mutation, and readiness failures no longer duplicate resource IDs.
Follow-up review caught a cross-subscription create-if-missing gap: setup now
rejects creating such an Update Instance during input/plan validation, before
namespace writes. Linking an existing cross-subscription instance remains supported.

## Validation scope and release qualification

The smoke and review results below describe the earlier feature qualification.
The 1.1 rebase preserves both release and feature test inventories; its current
head's checks are authoritative. No new live Azure onboarding run is claimed.

Local validation includes repository unit tests, focused regression tests, flake8,
pylint, and real-Azure smoke tests. Workflow smoke covers read-only tagged planning
and namespace setup/check/resume; radar smoke covers real provider reads and
headless read-only namespace navigation. Smoke resources use a dedicated owned
resource group and are removed afterward. Radar retains its 99% UI line-coverage gate.

This is **not full live Hub/DPS/Software Updates onboarding qualification**. Those
scenarios need a separately admitted live cohort with subscription capacity and
cleanup scheduling checked first. Offline coverage is not a substitute.
The final commit's current CI result is authoritative:
[workflow checks](https://github.com/Azure/azure-iot-cli-extension/pull/886/checks),
[radar checks](https://github.com/Azure/azure-iot-cli-extension/pull/875/checks).

## Remaining suggestions

1. **Expose RBAC repair in workflow plan review.** A matching link can be reported as satisfied while apply repairs missing service grants. The repair uses release authorization checks, but a future plan should show these grants explicitly rather than imply a zero-write reuse.
2. **Preflight predictable failures before creating prerequisites.** Validate existing targets' region, state, SKU, and the namespace SAMI needed by DPS as early as possible. Current provider validation prevents an invalid link, but some prerequisite resources may already exist when it rejects the operation.
3. **Prefer waiting for an already-pending radar link.** Radar can issue an update for a matching pending endpoint. Consider a wait-only step before retrying; no service rejection of this overlap was established in the smoke scope.
4. **Treat Registry Device browsing as a separate enhancement.** Release CLI support remains available, but adding it to radar is beyond the original UI scope.
5. **Merge independently and reconcile shared registrations afterward.** Both drafts add ADR command registration, release notes, and explicit integration inventory. The second PR may need a small refresh after the first merges; neither draft should silently absorb the other feature.
