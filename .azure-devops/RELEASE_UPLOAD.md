# Wheel upload results

The release pipeline never overwrites a wheel in Blob storage. Check the
**Wheel Blob upload** run summary or **Upload verified wheel** task logs.
The summary links to the Blob wheel and this run's `release-candidate` artifacts.
On a conflict, these are different files: the Blob link is the existing wheel,
not the rejected candidate.

| Result | Meaning | Action |
| --- | --- | --- |
| Uploaded and verified | The new wheel was uploaded and read back successfully. | Use the verified wheel link. |
| Identical wheel already exists | Size and SHA-256 match; upload was skipped. | No action needed. |
| `RELEASE_BLOB_CONFLICT` | This filename exists with different content. | Bump the version for changed content, or retry the upload/publish job in the original pipeline run with its approved artifact. |
| `RELEASE_BLOB_AUTH` | Storage authentication or authorization failed. | Check `sc-cli-release-storage` authentication and Blob data permissions. |
| `RELEASE_BLOB_UNVERIFIED` | A request or read-back could not establish the outcome. | The blob may already exist. Retry the original run's job with its approved artifact; do not delete or overwrite it. |
| `RELEASE_CANDIDATE_INVALID` | The candidate could not be validated against this run. | Follow the specific reason in the message; check pipeline variables and the candidate manifest. |

Rebuilding the same version can produce different wheel bytes. When sizes differ,
the existing SHA-256 is not computed: the files already cannot match.
Concurrent uploads succeed only after the stored bytes are verified as identical.
A mismatch after an accepted upload is reported as unverified, not as a pre-existing
conflict. Candidates are bound to the original run; do not import another run's
candidate to retry.

Expected upload errors fail the task with an ADO error code and a recovery summary,
without a Python traceback. Unexpected defects retain their traceback. A success
receipt is written only after verification. Summary links never include credentials
or SAS tokens; normal access restrictions still apply.

This branch retains the separate **Upload wheel only** mode. It does not create a
GitHub draft, release, tag, or index PR.
