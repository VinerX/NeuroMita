# Python build revisions inside an existing release

`2026.10.15` creates a normal release, `v2026.10.15`.
`2026.10.15.1`, `.2`, and subsequent numeric revisions replace the full Python
archive in that same release. They do not create another GitHub release or tag,
change its title, notes, publication date, or Latest status, or replace Unity.

## Initial deployment to Atm4x/NeuroMita

1. Apply the `release-manifest.yml` checkout change to the default branch (`main`).
   Its scheduled and release-event runs must check out `releases` for tooling.
   This is a separate deployment requirement: merging only into `releases` does
   not change a workflow that GitHub starts from `main`.
2. Merge the revision implementation into `releases`. The prepared
   `src/_version.py` is `2026.10.15.1`; the usual push trigger builds it.
3. Inspect the build and manifest jobs before declaring the revision available.

The runner change is intentionally independent of the Python changes and can be
cherry-picked into `main`. In other repositories the runner keeps using their
default branch. All publication and manifest rebuilds share the same concurrency
group; the build publishes its manifest directly, without calling a second
workflow while holding that group.

## Subsequent revisions

Change `src/_version.py` to the next revision and merge into `releases`.
Use a new revision number for changed binaries; rerunning an already published
version finishes publication/cleanup without rebuilding or overwriting it.
Revision numbers are compared numerically, so `.10` follows `.9`.

The base release must already exist, be published, stable, and mutable. A missing
base or immutable release is an error, not permission to create a new release.
A new date without a revision uses the normal release path.

The workflow builds in full mode, checks the release contract and embedded
`NeuroMita.pyz/_version.py`, uploads the new versioned ZIP, verifies its remote
size and SHA-256, and only then deletes previous Python ZIP/7z archives, including
obsolete differential patches. Other assets are retained. This ordering keeps
the previous download available if upload/verification fails. GitHub asset
replacement is not atomic: during upload/cleanup there can briefly be two Python
archives. After successful publication there is exactly one, so older clients
cannot accidentally choose an obsolete archive.

If deletion or manifest upload fails, rerun the workflow at the same version.
An already uploaded complete revision is retained and cleanup/manifest rebuilding
is retried. A different binary cannot replace an existing version silently.
The unchanged GitHub tag still points to the original source commit; the archive
distribution metadata records the actual build commit.

## Catalog and client compatibility

The artifact name is the source of build revision metadata. No sidecar revision
registry is required. Every rebuild of `releases-manifest.json` derives the same
effective version from `PythonBuild-vYYYY.MM.DD.N.zip`/`.7z`.

The public envelope remains **schema 1**. Installed `2026.10.15` clients reject a
new schema, so this feature is an additive extension, not a schema migration.
For a revision the catalog contains a Python-only entry with effective
`tag_name: v2026.10.15.1`, `release_tag: v2026.10.15`, `component: python`, and
`build_version: 2026.10.15.1`. Its asset URL points to the existing release.
The physical release entry retains non-Python assets under its original tag.
Thus existing clients detect the Python update without inventing a Unity update.
Manifest upload always targets the physical Latest release tag, never the virtual
build version. New clients apply the same filename inference to GitHub API
fallbacks, and news group entries into one card per physical release.

With a working manifest, a `2026.10.15` installation sees `.1`, then stops offering
it after installing a build whose embedded version is `.1`. If the manifest is
unavailable, the already installed old client cannot infer `.1` from GitHub API;
it can detect it again once the manifest is restored. New clients handle that API
fallback as well.

The `2026.08.31.1` updater checks the real release tag: it sees `v2026.10.15` as
newer, downloads the sole full `PythonBuild-v2026.10.15.1.zip`, and installs `.1`.
It may display the base tag in its update notification. Its name matching does
not require the archive version to equal the GitHub tag.
