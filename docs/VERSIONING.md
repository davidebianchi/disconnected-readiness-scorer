# Versioning Strategy for Disconnected Readiness Scorer

## Overview

The disconnected-readiness-scorer repository uses a **floating major version tag** strategy that balances security, usability, and automatic updates for downstream consumers.

## Versioning Scheme

### Semantic Versioning Foundation
All releases follow semantic versioning (semver) format: `v{MAJOR}.{MINOR}.{PATCH}`

- **MAJOR** (v1 → v2): Breaking changes to workflow inputs, outputs, or behavior
- **MINOR** (v1.0 → v1.1): New features, backward-compatible improvements
- **PATCH** (v1.0.0 → v1.0.1): Bug fixes, security updates, no breaking changes

### Tag Types

#### 1. Immutable Semantic Version Tags
- **Format**: `v1.0.0`, `v1.1.0`, `v2.0.0`
- **Purpose**: Exact version pinning for maximum control
- **Behavior**: Never updated after creation
- **Usage**: Conservative consumers who want explicit control over updates

#### 2. Floating Major Version Tags
- **Format**: `v1`, `v2`, `v3`
- **Purpose**: Automatic updates within major version boundaries
- **Behavior**: Automatically updated to point to latest release within major version
- **Usage**: Default recommendation for most consumers

### Floating Tag Guarantees

| Tag | Points To | Updates When | Guarantees |
|-----|-----------|--------------|------------|
| `v1` | Latest v1.x.x | Any v1.x.x release | No breaking changes |
| `v2` | Latest v2.x.x | Any v2.x.x release | Breaking changes from v1 |
| `v3` | Latest v3.x.x | Any v3.x.x release | Breaking changes from v2 |

## What Pinning Does and Does Not Cover

Pinning a consumer's `uses:` line (`@v1`, `@v1.2.3`, or a SHA) selects a version of the **reusable workflow file itself** — its steps and argument-building logic. It does not pin the scorer's Python code, and it does not pin `schemas/config.schema.json` either.

Inside the reusable workflow, the step that checks out the scorer's code (rules, `main.py`, `schemas/config.schema.json`, etc.) always uses the floating `v1` tag, regardless of which tier the caller's `uses:` line resolves to. This is deliberate: this repository's own automation (`create-drs-prs.yml`) is what writes and maintains the workflow file in every consumer repo, and it always writes `@v1`. Consumers are not expected to hand-edit that reference to a different tier. The actual gate on when new scorer code and its schema reach consumers is the release process itself — someone moving the `v1` tag forward — not a consumer's choice of pin.

`config/config.yaml` (exceptions, `docker_contexts`, `known_non_image_prefixes`, `params_env_filenames`) is **always fetched from `main`** at run time, regardless of which ref a consumer pins — including SHA-pinned consumers. Only the `exceptions` list carries a no-new-failure guarantee: it can only downgrade a `blocker` finding to `info`, never create a new finding or raise severity, so a live change to `exceptions` can't surprise a pinned consumer with a failure it didn't already have. The other three keys change scan behavior directly and can introduce findings that did not exist before: `docker_contexts` and `params_env_filenames` can widen which files or overlay directories get scanned, and narrowing or removing an entry in `known_non_image_prefixes` can un-suppress matches that were previously filtered out. A merged `exceptions` entry takes effect on the very next run, with no release required.

If `main`'s config references something the pinned code doesn't support (for example, an exception naming a rule that doesn't exist yet in that release's rule set), the run fails loudly with a validation error — there is no silent skip. The fix in that case is to release the **code** that understands the new config, not to work around it.

## Consumer Usage Patterns

### Recommended: Floating Major Version
```yaml
# Automatically receives patch and minor updates
uses: opendatahub-io/disconnected-readiness-scorer/.github/workflows/disconnected-readiness-check.yml@v1
```

**Benefits:**
- Automatic security patches (v1.0.0 → v1.0.1)
- Automatic feature updates (v1.0.0 → v1.1.0)
- No action needed for non-breaking changes
- Manual upgrade only for breaking changes (v1 → v2)

### Conservative: Explicit Version Pinning
```yaml
# Manual control over all updates
uses: opendatahub-io/disconnected-readiness-scorer/.github/workflows/disconnected-readiness-check.yml@v1.0.0
```

**Benefits:**
- Complete control over which version of the workflow's orchestration logic runs
- Manual work for security updates
- Manual work for bug fixes

**Not covered:** the scorer code this workflow checks out still tracks the floating `v1` tag internally — see [What Pinning Does and Does Not Cover](#what-pinning-does-and-does-not-cover). This tier is not the supported consumer pattern (see that section) and is not exercised by `create-drs-prs.yml`.

### Security-Focused: SHA Pinning
```yaml
# Maximum security, immutable reference
uses: opendatahub-io/disconnected-readiness-scorer/.github/workflows/disconnected-readiness-check.yml@d0bc6a3ce275e4d493891b25ffb822d0bddf7878
```

**Benefits:**
- The workflow file's orchestration logic is immutable and cannot be tampered with
- No automatic security updates to that logic
- Requires manual SHA updates

**Not covered:** this immutability applies to the workflow file only, not the scorer code it checks out (still tracks floating `v1`) or `config/config.yaml` (still fetched live from `main`) — see [What Pinning Does and Does Not Cover](#what-pinning-does-and-does-not-cover). This tier is not the supported consumer pattern and is not exercised by `create-drs-prs.yml`.

## Security Considerations

### Tag Management Policy
- **Semantic version tags** (v1.0.0) follow immutability policy - once created, they are never moved or updated
- **Floating major tags** (v1) are intentionally mutable - updated through the release workflow to point to latest release

### Supply Chain Security
- Release workflow requires elevated permissions
- Floating tags only move forward within major version boundaries
- Release process is auditable through GitHub Actions logs

### Compromise Mitigation
- If floating tag (`v1`) is compromised, consumers can pin to known-good semantic version
- Semantic version tags provide immutable fallback references
- SHA pinning available for maximum security environments

## Consumer Pinning Strategy

### The Balance: Reproducibility vs. Ease of Adoption

Our strategy provides both options to balance competing needs - teams choose the approach that fits their security and operational requirements.

## Release Information

Releases are managed through a manual GitHub Actions workflow that:
- Creates immutable semantic version tags (v1.2.3)  
- Updates floating major version tags (v1 → latest v1.x.x)
- Generates release notes and GitHub Releases

**For complete release procedures, see [RELEASE_PROCESS.md](RELEASE_PROCESS.md)**
