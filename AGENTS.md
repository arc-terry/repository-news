# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python command-line tool for generating Markdown reports from GitLab branch activity.

- `gitlab_branch_news.py` contains the CLI, GitLab API client, config loading, data collection, and Markdown rendering.
- `tests/test_gitlab_branch_news.py` contains unit tests using `unittest` and mocked HTTP responses.
- `config.yaml` is the checked-in default report configuration.
- `report/` is the generated output directory and is ignored by Git.
- `README.md` documents user-facing setup, run modes, and config fields.

Keep new source code close to the current single-module structure unless a change clearly benefits from splitting reusable logic into focused modules.

## Build, Test, and Development Commands

Install runtime dependencies:

```bash
python3 -m pip install requests pyyaml
```

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

Generate a report with the default config:

```bash
python3 gitlab_branch_news.py --config config.yaml
```

Write a deterministic local output while developing:

```bash
python3 gitlab_branch_news.py --config config.yaml --output report/latest.md --stdout
```

## Coding Style & Naming Conventions

Use standard Python 3 style with 4-space indentation, type hints where practical, and small functions with clear inputs and outputs. Existing names use `snake_case` for functions and variables, `PascalCase` for dataclasses and exceptions, and all-caps constants only when needed. Prefer structured parsing and dataclasses over ad hoc dictionaries for internal data.

## Testing Guidelines

Tests use the standard library `unittest` framework. Add tests under `tests/` with filenames matching `test_*.py` and test methods named `test_<behavior>`. Mock GitLab API calls with fake response/session objects rather than making network requests. Cover date/timezone formatting, config merging, pagination, error handling, and Markdown rendering when those areas change.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commits, for example `fix(report): use current time for default filename` and `chore: remove generated artifacts`. Use `<type>(optional-scope): <imperative subject>` and omit trailing periods.

Pull requests should include a short purpose summary, the commands run for verification, linked issues if applicable, and sample report output or screenshots when formatting changes.

## Security & Configuration Tips

Do not commit GitLab tokens, generated reports, or private certificate bundles. Provide credentials through `GITLAB_TOKEN`. Use `--ca-bundle` for internal certificates; reserve `--insecure` for temporary local runs only.
