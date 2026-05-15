# Copilot Instructions

## Build, test, and lint commands

- Install runtime dependencies: `python3 -m pip install requests pyyaml`
- Run with config file (preferred):
  `python3 gitlab_branch_news.py --config config.yaml`
- Run with CLI arguments (override config values):
  `python3 gitlab_branch_news.py --config config.yaml --branch <override_branch> --since <override_date>`
- Run with CLI only (no config):
  `python3 gitlab_branch_news.py --base-url <url> --group <group_path> --branch <branch> --since <YYYY-MM-DD> --until <YYYY-MM-DD>`
- Run full test suite: `python3 -m unittest discover -s tests -v`
- Run a single test:
  `python3 -m unittest tests.test_gitlab_branch_news.GitLabCollectionTests.test_collect_activity_handles_pagination_and_branch_filtering -v`

## High-level architecture

- `gitlab_branch_news.py` is a single-file CLI pipeline:
  `parse_args` -> `load_config` -> `merge_config_and_args` -> `validate_required_args` -> `collect_activity` -> `render_markdown` -> `write_output`.
- Config is loaded first from `--config`, then CLI arguments override any config values.
- `GitLabClient` encapsulates GitLab API behavior:
  - `_request_json` handles request timeout, TLS verify settings (`--insecure` / `--ca-bundle`), and translates HTTP/JSON issues into `GitLabReporterError`.
  - `_get_paginated` follows GitLab `X-Next-Page` headers and merges list payloads.
  - `list_tags` fetches all tags for a project to map commits to tags.
- Core immutable data models:
  - `ReportConfig` (config from YAML/JSON for CLI settings + overview/dev branch list)
  - `CommitEntry` (commit fields: sha, title, committed_at, web_url, branch, tags)
  - `ProjectActivity` (project path + branch + ordered commits)
- `collect_activity` is the orchestration layer:
  1. Resolve group metadata (`full_name`, `full_path`).
  2. Enumerate projects with `include_subgroups=true`.
  3. For each branch in `branches` list, check exact branch existence per project.
  4. Fetch commits in `[since, until]` and tags for projects with commits.
  5. Keep only projects with commits, sort commits oldest->newest, then sort projects by path depth/name.
- `tests/test_gitlab_branch_news.py` is the behavior spec. It uses `FakeSession`/`FakeResponse` to test pagination, branch filtering, tag mapping, config merging, formatting, output writing, and `main()` wiring without network access.

## Key conventions

- **Config-first parsing**: Config file is loaded first, then CLI arguments override config values. This allows storing defaults in config and overriding specific values per run.
- Config file can contain CLI settings: `base_url`, `group`, `branches`, `since`, `until`, `timezone`.
- Keep the Markdown table header label `Breif` exactly as-is; it is intentionally required by the report format.
- Datetime handling is two-phase and should not be mixed:
  - Input normalization (`parse_user_datetime`) converts `--since/--until` to UTC and expands date-only inputs to day bounds (`00:00:00` / `23:59:59`).
  - Output formatting (`format_year`, `format_week_count`, `format_short_date`, `format_sync_date`) applies the selected timezone only when rendering.
- `Sync. Date` in the report is the current execution time (when the script runs), not derived from `--until`.
- Branch matching is strict/exact. If a project does not contain the branch, emit a stderr warning and skip that project.
- Projects that have the branch but no commits in range are omitted from output entirely.
- Default output path is `report/<yyyy>_W<ww>_<mmdd>_<HHMMSS>.md` derived from the computer's current local time when the script runs. The `report/` directory is auto-created if missing.
- Auth must come from `GITLAB_TOKEN` in the environment (`PRIVATE-TOKEN` header).
- In this workspace, use `.git-repo` as Git metadata directory for Git commands:
  `git --git-dir=.git-repo --work-tree=. <command>`
