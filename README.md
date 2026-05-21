# Repo News Report

Generate a Markdown news report for selected GitLab repositories and branches.
The tool reads a YAML config, compares each configured `base_commit` to the
branch tip, and includes the base commit as the first row in each branch table.

## Quick Start

Install dependencies:

```bash
python3 -m pip install requests pyyaml
```

Set a GitLab token with read access to the target group and repositories:

```bash
export GITLAB_TOKEN="your_gitlab_token"
```

Run the report:

```bash
./repo-news-report.py config.yaml
```

By default, output is written to `report/<year>_W<week>_<mmdd>_<HHMMSS>.md`
using the computer's current local time for the filename.

## Common Commands

Write to a specific file:

```bash
./repo-news-report.py config.yaml --output report/latest.md
```

Also print the generated report:

```bash
./repo-news-report.py config.yaml --stdout
```

Use an internal certificate bundle:

```bash
./repo-news-report.py config.yaml --ca-bundle /path/to/company-ca.pem
```

Temporarily skip TLS verification for an internal run:

```bash
./repo-news-report.py config.yaml --insecure
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Generate a Config

Create a YAML config in one command with `gen-config.py`:

```bash
./gen-config.py \
  --output config.yaml \
  --base-url https://vcs-sw2.arcadyan.com.tw \
  --group kpn/v16-compact/guangzhou_gitlab_mirror \
  --timezone Asia/Taipei \
  --team "Hsinchu Team" \
  --group-path "KPN/V16 Compact/Guangzhou_GitLab_mirror" \
  --group-url https://vcs-sw2.arcadyan.com.tw/kpn/v16-compact/guangzhou_gitlab_mirror \
  --repo-branch prplos:arc-hsinchu/kpn-v16-compact=2634d949 \
  --repo-branch feeds/feed-qca:arc-hsinchu/dev-kpn-v16-compact_2026.05.15=25121e14
```

Repeat `--repo-branch REPO_PATH:BRANCH_NAME=BASE_COMMIT` for every branch.
Entries with the same repository path are grouped automatically.
You may also pass `--since` and `--until`; they are written to the config for
reference but are not required for repository compare reports.

## Config Format

`config.yaml` must be YAML and includes:

- `base_url`: GitLab server URL
- `group`: GitLab group path
- `since` / `until`: optional date window metadata
- `timezone`: IANA timezone used in the report
- `overview`: optional report overview fields
- `repositories`: repositories, branches, and base commits to compare

Example:

```yaml
base_url: "https://vcs-sw2.arcadyan.com.tw"
group: "kpn/v16-compact/guangzhou_gitlab_mirror"
timezone: "Asia/Taipei"

overview:
  team: "Hsinchu Team"
  group_path: "KPN/V16 Compact/Guangzhou_GitLab_mirror"
  group_url: "https://vcs-sw2.arcadyan.com.tw/kpn/v16-compact/guangzhou_gitlab_mirror"

repositories:
  - path: "prplos"
    branches:
      - name: "arc-hsinchu/kpn-v16-compact"
        base_commit: "2634d949"
```

## Report Output

The report includes a sync date, GitLab group overview, one section per
repository, a base commit table, and a commit table for each configured branch.
Commit rows show `Year`, `Week`, `Date`, short commit SHA, GitLab link, tag, and
`Breif`. `Breif` is intentionally spelled that way to match the requested report
format.
