# GitLab Branch News Reporter

Generate a Markdown report for selected GitLab repositories and branches.

The current default mode uses `config.yaml`. For each repository branch, the tool compares a configured `base_commit` to the branch tip and includes the base commit as the first row.

## Setup

Install dependencies:

```bash
python3 -m pip install requests pyyaml
```

Set your GitLab token:

```bash
export GITLAB_TOKEN="your_gitlab_token"
```

The token must be able to read the target GitLab group and repositories.

## Run

Use the checked-in config:

```bash
python3 gitlab_branch_news.py --config config.yaml
```

By default, the report is written to:

```text
report/<year>_W<week>_<mmdd>_<HHMMSS>.md
```

The filename uses the computer's current local time when the script runs.

Write to a specific file:

```bash
python3 gitlab_branch_news.py --config config.yaml --output report/latest.md
```

Also print the report to the terminal:

```bash
python3 gitlab_branch_news.py --config config.yaml --stdout
```

For an internal certificate:

```bash
python3 gitlab_branch_news.py --config config.yaml --ca-bundle /path/to/company-ca.pem
```

For a temporary internal run without TLS verification:

```bash
python3 gitlab_branch_news.py --config config.yaml --insecure
```

## Config

`config.yaml` contains:

- `base_url`: GitLab server URL
- `group`: GitLab group path
- `timezone`: timezone used in the report
- `overview`: text shown in the report overview
- `repositories`: repositories, branches, and base commits to report

Example repository entry:

```yaml
repositories:
  - path: "prplos"
    branches:
      - name: "arc-hsinchu/kpn-v16-compact"
        base_commit: "2634d949"
      - name: "arc-hsinchu/dev-kpn-v16-compact_2026.05.15"
        base_commit: "c4b31665"
```

## Output

The report includes:

- sync date
- GitLab group overview
- one section per repository
- a base commit table for each repository
- one commit table per configured branch

Commit table fields:

- `Year`, `Week`, `Date`: commit date in the configured timezone
- `Commit`: short SHA
- `Link`: GitLab commit link
- `Tag`: tags on the commit, or `-`
- `Breif`: commit title

`Breif` is intentionally spelled this way to match the requested report format.

## Legacy Mode

The script still supports the old CLI mode:

```bash
python3 gitlab_branch_news.py \
  --base-url https://vcs-sw2.arcadyan.com.tw \
  --group kpn/v16-compact/guangzhou_gitlab_mirror \
  --branch arc-hsinchu/kpn-v16-compact \
  --since 2026-05-05 \
  --until 2026-05-13 \
  --timezone Asia/Taipei
```

Legacy mode scans projects in the group and collects commits in the date window.

## Tests

Run:

```bash
python3 -m unittest discover -s tests -v
```
