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
| `RELEASE_BLOB_CONFLICT` | This filename exists with different content. | Bump the version for changed content, or reuse the original approved artifact for a retry. |
| `RELEASE_BLOB_AUTH` | Storage authentication or authorization failed. | Check `sc-cli-release-storage` authentication and Blob data permissions. |
| `RELEASE_BLOB_UNVERIFIED` | A request or read-back could not establish the outcome. | The blob may already exist. Retry with the same approved artifact; do not delete or overwrite it. |
| `RELEASE_CANDIDATE_INVALID` | The local candidate or manifest failed validation. | Inspect this run's candidate artifact and manifest before retrying. |

Rebuilding the same version can produce different wheel bytes. When sizes differ,
the existing SHA-256 is not computed: the files already cannot match.
Concurrent uploads succeed only after the stored bytes are verified as identical.

Expected upload errors fail the task with an ADO error code and a recovery summary,
without a Python traceback. Unexpected defects retain their traceback. A failed
upload blocks downstream release/index publication in that job. A success receipt
is written only after verification. Summary links never include credentials or SAS
tokens; normal access restrictions still apply.
