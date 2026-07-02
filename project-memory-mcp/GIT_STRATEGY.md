# Git Branching Strategy for project-memory-mcp

## Overview

This project uses **Trunk-Based Development** with short-lived feature branches.

### Why Trunk-Based Development?

- **Single source of truth**: `main` branch is always deployable
- **Fast feedback**: CI runs on every commit
- **Avoids merge conflicts**: Short-lived branches (< 1 day) mean less divergence
- **Enables continuous delivery**: Features can be released independently via feature flags
- **Proven at scale**: Used by Google, Facebook, and other large organizations

## Branch Structure

```
main (protected, always deployable)
  ├── feature/* (short-lived, < 1 day)
  ├── bugfix/* (short-lived, < 1 day)
  ├── release/v* (just-in-time, deleted after release)
  ├── hotfix/v*-* (from release tag, merged to main + release)
  ├── docs/* (documentation updates)
  ├── chore/* (maintenance tasks)
  └── experiment/* (research spikes, may be abandoned)
```

## Branch Naming Conventions

| Prefix | Purpose | Format | Example |
|--------|---------|--------|---------|
| `feature/` | New functionality | `feature/<subsystem>-<description>` | `feature/static_analysis-add-rust-support` |
| `bugfix/` | Bug fixes | `bugfix/<subsystem>-<issue-id>` | `bugfix/db-connection-pool-leak` |
| `release/` | Release preparation | `release/v<major>.<minor>.<patch>` | `release/v1.0.0` |
| `hotfix/` | Production hotfixes | `hotfix/<version>-<issue-id>` | `hotfix/v1.0.1-cve-2026-fix` |
| `docs/` | Documentation | `docs/<topic>` | `docs/api-reference` |
| `chore/` | Maintenance | `chore/<task>` | `chore/update-dependencies` |
| `experiment/` | Research spikes | `experiment/<idea>` | `experiment/kuzudb-migration` |

### Subsystem Names
- `server` - MCP server and transport
- `static` - Static analysis (tree-sitter, file scanner)
- `llm` - LLM analysis pipeline
- `db` - Database and models
- `workflow` - Workflow orchestration
- `tools` - MCP tools
- `cli` - CLI interface
- `dashboard` - Web dashboard (Phase 4)

## Protected Branch Rules (GitHub/GitLab)

### `main` Branch
- ✅ Require pull request before merging
- ✅ Require status checks to pass:
  - `lint` (ruff)
  - `typecheck` (pyright)
  - `test` (pytest)
  - `migration_check` (alembic check)
- ✅ Require 1+ approving reviews
- ✅ Require linear history (squash merge)
- ✅ No force pushes
- ✅ No direct commits

### `release/*` Branches
- ✅ Require pull request
- ✅ Require status checks to pass (same as main)
- ✅ Require 2+ approving reviews for non-hotfix releases
- ✅ No force pushes

## CODEOWNERS

```
# Global owners (review all changes)
* @core-maintainers

# Subsystem owners
/src/project_memory_mcp/server/ @server-team
/src/project_memory_mcp/static_analysis/ @static-analysis-team
/src/project_memory_mcp/llm_analysis/ @llm-team
/src/project_memory_mcp/db/ @db-team
/src/project_memory_mcp/workflows/ @workflow-team
/src/project_memory_mcp/mcp_tools/ @tools-team
/src/project_memory_mcp/cli/ @cli-team

# Shared utilities
/src/project_memory_mcp/utils/ @core-maintainers

# Configuration
/pyproject.toml @core-maintainers
/alembic.ini @db-team
/.github/workflows/ @core-maintainers
```

## Commit Message Convention

```
<type>(<subsystem>): <description>

[optional body]

[optional footer]
```

### Types
| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation |
| `style` | Formatting, no code change |
| `refactor` | Code restructuring |
| `perf` | Performance improvement |
| `test` | Adding/updating tests |
| `build` | Build system changes |
| `ci` | CI/CD changes |
| `chore` | Maintenance |
| `revert` | Reverting a commit |

### Subsystem Tags
`server`, `static`, `llm`, `db`, `workflow`, `tools`, `cli`, `dashboard`

### Examples
```
feat(static): add Rust language support via tree-sitter
fix(db): resolve connection pool leak in HTTP transport
refactor(llm)!: migrate from instructor v1 to v2 API
docs(cli): update command reference
test(workflow): add integration test for impact analysis
chore(deps): update dependencies to latest
```

### Breaking Changes
```
refactor(db)!: change database schema for equations

BREAKING CHANGE: Equation table structure changed.
Migration required: run `alembic upgrade head`.
```

## Pull Request Workflow

### PR Template
```markdown
## Description
Brief description of changes.

## Related Issues
Fixes #123, Closes #456

## Subsystem(s) Affected
- [ ] server
- [ ] static
- [ ] llm
- [ ] db
- [ ] workflow
- [ ] tools
- [ ] cli
- [ ] dashboard

## Checklist
- [ ] Code follows project conventions (typechecked, linted)
- [ ] Tests added/updated
- [ ] DB migrations included (if schema changed)
- [ ] MCP tool schema updated (if tool signature changed)
- [ ] Documentation updated
- [ ] Manual tested locally (`uv run mcp dev`)
- [ ] Breaking changes documented in footer

## Testing
Describe how this was tested.
```

### Required CI Checks
All must pass before merge:
1. `ruff check` - Linting
2. `pyright` - Type checking
3. `pytest` - Unit + integration tests
4. `alembic check` - Migration check

### Merge Strategy
- **Squash and merge only** - maintains linear history on `main`
- Auto-delete branch after merge
- PR title becomes commit message

## Release Process

### Versioning
Semantic Versioning: `MAJOR.MINOR.PATCH`

### Release Checklist
1. Create `release/vX.Y.Z` branch from `main`
2. Update version in `pyproject.toml`
3. Update `CHANGELOG.md`
4. Run full test suite
5. Create GitHub release with tag `vX.Y.Z`
6. Merge `release/vX.Y.Z` → `main` (squash)
7. Delete `release/vX.Y.Z` branch
8. Deploy package

### Release Cadence
- MVP (Phase 1): Every 2 weeks
- Stable: Monthly

## CI/CD Pipeline

### GitHub Actions Workflows
```
.github/workflows/
├── ci.yml              # PR + push to main: lint, typecheck, test, migration check
├── release.yml         # Release branch: full test suite + build + publish
├── dependency-updates.yml  # Weekly: Dependabot PRs
└── codeql.yml          # Weekly: Security analysis
```

### CI Matrix
- Python: 3.10, 3.11, 3.12, 3.13
- OS: ubuntu-latest, windows-latest, macos-latest (minimum ubuntu + one more)

## Multi-Team Coordination

### Feature Flags
For incomplete work that spans multiple subsystems:
```python
# config/feature_flags.py
ENABLE_RUST_SUPPORT = os.getenv("PMM_ENABLE_RUST", "false").lower() == "true"
ENABLE_EQUATION_GRAPH = os.getenv("PMM_ENABLE_EQ_GRAPH", "false").lower() == "true"
```

### Branch by Abstraction
For large cross-subsystem refactors:
1. Introduce abstraction layer
2. Migrate subsystems one at a time
3. Remove old implementation
4. Remove abstraction layer

### Sync Meetings
- Weekly: Subsystem lead sync (30 min)
- Daily: Async standup in PR comments
- Nightly: Full integration test on `main`

## Git Hooks (pre-commit)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-pyright
    rev: v1.1.384
    hooks:
      - id: pyright

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: detect-private-key
      - id: detect-aws-credentials
      - id: trailing-whitespace
      - id: end-of-file-fixer
```

## Tag Convention

| Tag Type | Format | Example |
|----------|--------|---------|
| Stable release | `v<MAJOR>.<MINOR>.<PATCH>` | `v1.0.0` |
| Release candidate | `v<MAJOR>.<MINOR>.<PATCH>-rc<N>` | `v1.0.0-rc1` |

**Only annotated tags**: `git tag -a v1.0.0 -m "Release v1.0.0: Initial MVP"`

## Quick Reference

```bash
# Start a feature
git checkout main && git pull
git checkout -b feature/static-add-rust-support

# Work on feature (commit often)
git add . && git commit -m "feat(static): add Rust parser"

# Push and create PR
git push -u origin feature/static-add-rust-support
# Create PR via GitHub

# After PR approved and CI passes
# Squash merge via GitHub UI
# Branch auto-deleted

# For hotfix
git checkout v1.0.0  # tag
git checkout -b hotfix/v1.0.1-fix-bug
# ... fix ...
git commit -m "fix(db): resolve connection leak"
# Push, PR to release/v1.0.0, merge
# Then PR to main, merge
```