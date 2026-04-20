# Release and Versioning Policy

Bluetooth-2-USB uses `setuptools_scm` to derive package versions from Git tags.

This project treats **official releases** and **development builds** differently:

- official releases follow SemVer
- development builds use SCM-derived PEP 440 versions between releases

## Official release format

Official release tags must use:

```text
vMAJOR.MINOR.PATCH
```

Examples:

- `v1.0.0`
- `v1.0.1`
- `v1.1.0`
- `v2.0.0`

Only tags that match that exact pattern count as release tags for package versioning.

That means helper tags such as:

- `hardening-test-install-2026-04-05`
- `test-foo`
- `release-candidate`

are ignored by the package version logic.

## SemVer rules

Starting with the `1.0.0` release, official releases follow SemVer:

- `PATCH`
  Bug fixes, diagnostics improvements, compatibility fixes, packaging fixes, and other backward-compatible corrections.
- `MINOR`
  Backward-compatible new features, new supported workflows, new CLI options, or expanded hardware/runtime support.
- `MAJOR`
  Breaking changes to CLI behavior, configuration files, installer/runtime contracts, supported operational model, or other externally visible compatibility boundaries.

## Development builds

Between release tags, the package version is derived from Git history.

Typical examples:

- `1.0.1.dev3+gabc1234.d20260406`
- `1.1.1.dev7+gdef5678.d20260406`

These development versions are intentionally PEP 440 compliant rather than pure SemVer strings.
The SemVer contract applies to official release tags such as `v1.0.0`, `v1.0.1`, and `v1.1.0`.

These versions are for development, testing, and traceability. They are not official releases.

## Why this repo uses `setuptools_scm`

This avoids hard-coded version strings in runtime code and keeps these outputs aligned:

- `python -m bluetooth_2_usb --version`
- package metadata
- wheels and source distributions
- installed service/runtime logs

The managed `/opt/bluetooth_2_usb` clone-based install remains compatible with
that versioning model. The installer rebuilds the venv from the checked-out Git
tree in `/opt/bluetooth_2_usb`, so an install from the exact tagged commit will
show that exact release version. A separate tarball install is not required for
the runtime to report `1.0.0`.

In practice:

- install from checkout at tag `v1.0.0` -> runtime version `1.0.0`
- install from later commits after `v1.0.0` -> SCM-derived development version

## Release process

For an official release:

1. Merge the intended changes into `main`
2. Ensure the branch is clean and tested
3. Create an annotated SemVer tag
4. Push the tag
5. Publish the GitHub release and any attached repository build artifacts

Release notes should describe the current supported product surface only:

- clone-based installation into `/opt/bluetooth_2_usb`
- updates via `/opt/bluetooth_2_usb/scripts/update.sh`
- diagnostics via `--validate-env`, `smoketest.sh`, and `debug.sh`
- persistent read-only operation only when a separate writable ext4 filesystem
  is configured for Bluetooth state

Example:

```bash
git switch main
git pull --ff-only origin main
git tag -a v1.0.0 -m "Bluetooth-2-USB 1.0.0"
git push origin v1.0.0
```

## History rewrites and tag ancestry

Bluetooth-2-USB derives development versions from the most recent reachable
release tag. If `main` history is rewritten, the latest official release tag
must be re-anchored to the content-equivalent commit on the rewritten history.

Otherwise `setuptools_scm` can fall back to an incorrect base version such as
`0.0`, and development builds will no longer advance from the real last release.

## Test tags

Use non-release-like tags for temporary validation work, especially in test repositories.

Good examples:

- `hardening-test-install-2026-04-05`
- `pi-validation-2026-04-06`

Do not create throwaway tags that look like official releases unless you actually intend to ship that release.
