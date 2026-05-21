#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class GitLabReporterError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchConfig:
    name: str
    base_commit: str


@dataclass(frozen=True)
class RepositoryConfig:
    path: str
    branches: tuple[BranchConfig, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReportConfig:
    """Configuration loaded from the positional YAML config file."""
    # CLI settings (can be overridden by command line)
    base_url: str = ""
    group: str = ""
    branches: tuple[str, ...] = field(default_factory=tuple)
    since: str = ""
    until: str = ""
    timezone: str = "Asia/Taipei"
    # Report-only settings
    team: str = ""
    group_path: str = ""
    group_url: str = ""
    development_branches: tuple[dict[str, str], ...] = field(default_factory=tuple)
    branch_naming_rule: str = ""
    repositories: tuple[RepositoryConfig, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitEntry:
    sha: str
    title: str
    committed_at: datetime
    web_url: str
    branch: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProjectActivity:
    relative_path: str
    branch: str
    commits: tuple[CommitEntry, ...]
    base_commit: str = ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown repository news report from a YAML config."
    )
    parser.add_argument(
        "config_path",
        help="Path to the YAML config file.",
    )
    parser.add_argument(
        "--output",
        help="Markdown output path. If omitted, a filename is generated automatically.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the generated Markdown report to stdout.",
    )
    parser.add_argument("--ca-bundle", help="Path to a custom CA bundle for TLS verification")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    return parser.parse_args(argv)


def load_config(config_path: str | None) -> ReportConfig:
    if not config_path:
        return ReportConfig()
    if not config_path.endswith((".yaml", ".yml")):
        raise GitLabReporterError("Config file must be YAML (.yaml or .yml)")
    with open(config_path, encoding="utf-8") as handle:
        content = handle.read()
    if not HAS_YAML:
        raise GitLabReporterError("PyYAML is required to load YAML config files (pip install pyyaml)")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise GitLabReporterError("Config file must contain a YAML object")
    overview = data.get("overview", {})
    dev_branches = data.get("development_branch_list", [])
    branches_raw = data.get("branches", [])
    if isinstance(branches_raw, str):
        branches_raw = [branches_raw]
    repositories_raw = data.get("repositories", [])
    repositories: list[RepositoryConfig] = []
    if isinstance(repositories_raw, list):
        for repo_raw in repositories_raw:
            if not isinstance(repo_raw, dict):
                continue
            repo_branches: list[BranchConfig] = []
            for branch_raw in repo_raw.get("branches", []):
                if not isinstance(branch_raw, dict):
                    continue
                name = str(branch_raw.get("name", branch_raw.get("branch", ""))).strip()
                base_commit = str(branch_raw.get("base_commit", "")).strip()
                if name and base_commit:
                    repo_branches.append(BranchConfig(name=name, base_commit=base_commit))
            repo_path = str(repo_raw.get("path", "")).strip("/")
            if repo_path and repo_branches:
                repositories.append(RepositoryConfig(path=repo_path, branches=tuple(repo_branches)))
    return ReportConfig(
        base_url=str(data.get("base_url", "")),
        group=str(data.get("group", "")),
        branches=tuple(branches_raw) if isinstance(branches_raw, list) else (),
        since=str(data.get("since", "")),
        until=str(data.get("until", "")),
        timezone=str(data.get("timezone", "Asia/Taipei")),
        team=str(overview.get("team", "")),
        group_path=str(overview.get("group_path", "")),
        group_url=str(overview.get("group_url", "")),
        development_branches=tuple(dev_branches) if isinstance(dev_branches, list) else (),
        branch_naming_rule=str(data.get("branch_naming_rule", "")),
        repositories=tuple(repositories),
    )


def validate_required_args(args: argparse.Namespace, *, require_branches: bool = True) -> None:
    """Validate that all required arguments are present after merging config."""
    missing = []
    if not getattr(args, "base_url", ""):
        missing.append("--base-url")
    if not getattr(args, "group", ""):
        missing.append("--group")
    if require_branches and not getattr(args, "branches", None):
        missing.append("--branch")
    require_date_bounds = require_branches
    if require_date_bounds and not getattr(args, "since", ""):
        missing.append("--since")
    if require_date_bounds and not getattr(args, "until", ""):
        missing.append("--until")
    if missing:
        raise GitLabReporterError(f"Missing required arguments: {', '.join(missing)}")


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def parse_gitlab_datetime(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10:
        return datetime.fromisoformat(text).replace(tzinfo=UTC)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def parse_user_datetime(value: str, *, end_of_day: bool) -> datetime:
    text = value.strip()
    if len(text) == 10:
        suffix = "T23:59:59+00:00" if end_of_day else "T00:00:00+00:00"
        text = text + suffix
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_gitlab_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def format_filename_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d")


def format_report_date(value: datetime, timezone: ZoneInfo) -> str:
    return value.astimezone(timezone).strftime("%m%d%Y")


def format_week_count(value: datetime, timezone: ZoneInfo) -> str:
    week = value.astimezone(timezone).isocalendar().week
    return f"W{week:02d}"


def short_sha(value: str) -> str:
    return value[:8]


def encode_path(value: str) -> str:
    return quote(value, safe="")


def slugify_filename_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "gitlab"


def default_output_path() -> str:
    now = datetime.now()
    year = now.strftime("%Y")
    week = f"W{now.isocalendar().week:02d}"
    date = now.strftime("%m%d")
    time = now.strftime("%H%M%S")
    return f"report/{year}_{week}_{date}_{time}.md"


def build_headers(token: str) -> dict[str, str]:
    return {"PRIVATE-TOKEN": token}


class GitLabClient:
    def __init__(self, base_url: str, token: str, *, verify: str | bool, session: requests.Session | None = None):
        self.base_url = normalize_base_url(base_url)
        self.verify = verify
        self.session = session or requests.Session()
        self.session.headers.update(build_headers(token))

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, verify=self.verify, timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("message"):
                    detail = f": {payload['message']}"
            except ValueError:
                detail = ""
            raise GitLabReporterError(f"GitLab API request failed for {url} ({response.status_code}){detail}") from exc
        try:
            return response.json(), response.headers
        except ValueError as exc:
            raise GitLabReporterError(f"GitLab API returned non-JSON data for {url}") from exc

    def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        page = 1
        merged = dict(params or {})
        merged.setdefault("per_page", 100)
        items: list[Any] = []
        while True:
            merged["page"] = page
            payload, headers = self._request_json(path, merged)
            if not isinstance(payload, list):
                raise GitLabReporterError(f"Expected list response for {path}")
            items.extend(payload)
            next_page = headers.get("X-Next-Page", "")
            if not next_page:
                break
            page = int(next_page)
        return items

    def get_group(self, group: str) -> dict[str, Any]:
        payload, _ = self._request_json(f"/api/v4/groups/{encode_path(group)}")
        if not isinstance(payload, dict):
            raise GitLabReporterError("Expected object response for group lookup")
        return payload

    def list_group_projects(self, group: str) -> list[dict[str, Any]]:
        items = self._get_paginated(
            f"/api/v4/groups/{encode_path(group)}/projects",
            params={"include_subgroups": "true", "with_shared": "false"},
        )
        return [item for item in items if isinstance(item, dict)]

    def get_project(self, project_path: str) -> dict[str, Any]:
        payload, _ = self._request_json(f"/api/v4/projects/{encode_path(project_path)}")
        if not isinstance(payload, dict):
            raise GitLabReporterError("Expected object response for project lookup")
        return payload

    def get_branch(self, project_id: int, branch: str) -> dict[str, Any] | None:
        try:
            payload, _ = self._request_json(
                f"/api/v4/projects/{project_id}/repository/branches/{encode_path(branch)}"
            )
        except GitLabReporterError as exc:
            if "(404)" in str(exc):
                return None
            raise
        if not isinstance(payload, dict):
            raise GitLabReporterError("Expected object response for branch lookup")
        return payload

    def get_commit(self, project_id: int, commit_ref: str) -> dict[str, Any]:
        payload, _ = self._request_json(
            f"/api/v4/projects/{project_id}/repository/commits/{encode_path(commit_ref)}"
        )
        if not isinstance(payload, dict):
            raise GitLabReporterError("Expected object response for commit lookup")
        return payload

    def compare_commits(self, project_id: int, from_ref: str, to_ref: str) -> list[dict[str, Any]]:
        payload, _ = self._request_json(
            f"/api/v4/projects/{project_id}/repository/compare",
            params={"from": from_ref, "to": to_ref},
        )
        if not isinstance(payload, dict):
            raise GitLabReporterError("Expected object response for compare lookup")
        commits = payload.get("commits", [])
        if not isinstance(commits, list):
            raise GitLabReporterError("Expected list of commits in compare response")
        return [item for item in commits if isinstance(item, dict)]

    def list_commits(self, project_id: int, branch: str, since: datetime, until: datetime) -> list[dict[str, Any]]:
        items = self._get_paginated(
            f"/api/v4/projects/{project_id}/repository/commits",
            params={
                "ref_name": branch,
                "since": format_gitlab_timestamp(since),
                "until": format_gitlab_timestamp(until),
            },
        )
        return [item for item in items if isinstance(item, dict)]

    def list_tags(self, project_id: int) -> list[dict[str, Any]]:
        items = self._get_paginated(f"/api/v4/projects/{project_id}/repository/tags")
        return [item for item in items if isinstance(item, dict)]

    def list_commit_branch_refs(self, project_id: int, sha: str) -> list[dict[str, Any]]:
        items = self._get_paginated(
            f"/api/v4/projects/{project_id}/repository/commits/{encode_path(sha)}/refs",
            params={"type": "branch"},
        )
        return [item for item in items if isinstance(item, dict)]


def build_tag_map(tags: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build a mapping from commit SHA to list of tag names."""
    sha_to_tags: dict[str, list[str]] = {}
    for tag in tags:
        commit = tag.get("commit", {})
        sha = str(commit.get("id", ""))
        name = str(tag.get("name", ""))
        if sha and name:
            sha_to_tags.setdefault(sha, []).append(name)
    return sha_to_tags


def project_relative_path(project: dict[str, Any], group_full_path: str) -> str:
    full_path = str(project.get("path_with_namespace", "")).strip("/")
    prefix = group_full_path.strip("/") + "/"
    if full_path.startswith(prefix):
        return full_path[len(prefix) :]
    return str(project.get("path", full_path))


def project_sort_key(relative_path: str) -> tuple[int, str]:
    return (relative_path.count("/"), relative_path.lower())


def collect_activity(
    client: GitLabClient,
    *,
    group: str,
    branches: list[str],
    since: datetime,
    until: datetime,
    stderr: Any,
) -> tuple[str, list[ProjectActivity]]:
    group_info = client.get_group(group)
    group_title = f"{group_info['full_name']} Group"
    group_full_path = str(group_info["full_path"])
    projects = client.list_group_projects(group)
    discovered: list[ProjectActivity] = []
    for project in projects:
        project_id = int(project["id"])
        relative_path = project_relative_path(project, group_full_path)
        tag_map: dict[str, list[str]] | None = None
        for branch in branches:
            branch_info = client.get_branch(project_id, branch)
            if branch_info is None:
                print(f"warning: branch '{branch}' not found in project '{relative_path}', skipping", file=stderr)
                continue
            commits_raw = client.list_commits(project_id, branch, since, until)
            if not commits_raw:
                continue
            if tag_map is None:
                tag_map = build_tag_map(client.list_tags(project_id))
            commits = tuple(
                CommitEntry(
                    sha=str(item["id"]),
                    title=str(item["title"]),
                    committed_at=parse_gitlab_datetime(str(item["committed_date"])),
                    web_url=str(item["web_url"]),
                    branch=branch,
                    tags=tuple(tag_map.get(str(item["id"]), [])),
                )
                for item in commits_raw
            )
            ordered = tuple(sorted(commits, key=lambda item: item.committed_at))
            discovered.append(ProjectActivity(relative_path=relative_path, branch=branch, commits=ordered))
    discovered.sort(key=lambda item: project_sort_key(item.relative_path))
    return group_title, discovered


def commit_from_api_payload(
    item: dict[str, Any],
    *,
    tag_map: dict[str, list[str]],
    branch_refs: tuple[str, ...],
) -> CommitEntry:
    sha = str(item["id"])
    title = str(item["title"])
    date_value = str(item.get("committed_date", item.get("committed_at", "")))
    branch = ", <br>".join(branch_refs) if branch_refs else "-"
    return CommitEntry(
        sha=sha,
        title=title,
        committed_at=parse_gitlab_datetime(date_value),
        web_url=str(item["web_url"]),
        branch=branch,
        tags=tuple(tag_map.get(sha, [])),
    )


def collect_configured_activity(
    client: GitLabClient,
    *,
    config: ReportConfig,
    stderr: Any,
) -> list[ProjectActivity]:
    discovered: list[ProjectActivity] = []
    group = config.group.strip("/")
    for repo_config in config.repositories:
        project_path = f"{group}/{repo_config.path.strip('/')}"
        project = client.get_project(project_path)
        project_id = int(project["id"])
        tag_map: dict[str, list[str]] | None = None
        for branch_config in repo_config.branches:
            branch_info = client.get_branch(project_id, branch_config.name)
            if branch_info is None:
                print(
                    f"warning: branch '{branch_config.name}' not found in project '{repo_config.path}', skipping",
                    file=stderr,
                )
                continue
            base_commit = client.get_commit(project_id, branch_config.base_commit)
            compare_commits = client.compare_commits(project_id, branch_config.base_commit, branch_config.name)
            if tag_map is None:
                tag_map = build_tag_map(client.list_tags(project_id))
            commits_raw = [base_commit, *compare_commits]
            seen: set[str] = set()
            commits: list[CommitEntry] = []
            for item in commits_raw:
                sha = str(item["id"])
                if sha in seen:
                    continue
                seen.add(sha)
                branch_refs_raw = client.list_commit_branch_refs(project_id, sha)
                branch_refs = tuple(str(ref.get("name", "")) for ref in branch_refs_raw if ref.get("name"))
                commits.append(commit_from_api_payload(item, tag_map=tag_map, branch_refs=branch_refs))
            ordered = tuple(sorted(commits, key=lambda item: item.committed_at))
            if ordered:
                discovered.append(
                    ProjectActivity(
                        relative_path=repo_config.path,
                        branch=branch_config.name,
                        commits=ordered,
                        base_commit=short_sha(base_commit["id"]),
                    )
                )
    return discovered


def format_sync_date(dt: datetime, timezone: ZoneInfo) -> str:
    local_dt = dt.astimezone(timezone)
    am_pm = "AM" if local_dt.hour < 12 else "PM"
    return local_dt.strftime(f"%m%d%Y {am_pm} %I:%M")


def format_year(dt: datetime, timezone: ZoneInfo) -> str:
    return dt.astimezone(timezone).strftime("%Y")


def format_short_date(dt: datetime, timezone: ZoneInfo) -> str:
    return dt.astimezone(timezone).strftime("%m%d")


def format_tag_string(tags: tuple[str, ...], *, configured: bool) -> str:
    if not tags:
        return "-"
    separator = ", <br>" if configured else ", "
    return separator.join(tags)


def gitlab_link_label(group_path: str) -> str:
    label = group_path.strip("/").split("/")[-1] if group_path else "Group"
    return f"{label} · GitLab"


def append_configured_overview(lines: list[str], group_title: str, config: ReportConfig | None) -> None:
    lines.append("## Overview")
    lines.append("")
    if config and config.team:
        lines.append(f"{config.team}:")
        lines.append("")
    group_path = config.group_path if config and config.group_path else group_title
    if not group_path.endswith(" Group"):
        group_path = f"{group_path} Group"
    lines.append("| Name              | Content |")
    lines.append("| ----------------- | ------- |")
    lines.append(f"| GitLab Group Path | {group_path} |")
    if config and config.group_url:
        lines.append(f"| GitLab Group URL  | [{gitlab_link_label(config.group_path)}]({config.group_url}) |")
    lines.append("")


def append_configured_repository(lines: list[str], rel_path: str, activities: list[ProjectActivity], timezone: ZoneInfo) -> None:
    lines.append(f"### {rel_path}")
    lines.append("")
    lines.append("| No. | Base Commit | Branch Name |")
    lines.append("| --- | ----------- | ----------- |")
    for index, activity in enumerate(activities, start=1):
        lines.append(f"| {index:<3} | {activity.base_commit:<11} | {activity.branch} |")
    lines.append("")
    for activity in activities:
        lines.append(f"#### {activity.branch}")
        lines.append("")
        lines.append("| No. | Year | Week | Date | Commit   | Link | Tag | Breif |")
        lines.append("| --- | ---- | ---- | ---- | -------- | ---- | --- | ----- |")
        for index, commit in enumerate(activity.commits):
            year = format_year(commit.committed_at, timezone)
            week = format_week_count(commit.committed_at, timezone)
            date = format_short_date(commit.committed_at, timezone)
            title = commit.title.replace("\n", " ").strip()
            commit_id = short_sha(commit.sha)
            tag_str = format_tag_string(commit.tags, configured=True)
            lines.append(
                f"| {index:<3} | {year} | {week:<4} | {date} | {commit_id} | [link]({commit.web_url}) | {tag_str:<3} | {title} |"
            )
        lines.append("")


def render_markdown(
    group_title: str,
    projects: Iterable[ProjectActivity],
    timezone: ZoneInfo,
    *,
    config: ReportConfig | None = None,
    configured: bool = False,
) -> str:
    lines: list[str] = []
    now = datetime.now(UTC)
    if not configured:
        lines.append("```table-of-contents")
        lines.append("```")
    lines.append(f"Sync. Date: {format_sync_date(now, timezone)}")
    if configured:
        append_configured_overview(lines, group_title, config)
        lines.append("## Repositories")
        lines.append("")
        grouped_configured: dict[str, list[ProjectActivity]] = {}
        for project in projects:
            grouped_configured.setdefault(project.relative_path, []).append(project)
        for rel_path, activities in grouped_configured.items():
            append_configured_repository(lines, rel_path, activities, timezone)
        return "\n".join(lines).rstrip() + "\n"

    lines.append("## Overview")
    lines.append("")
    if config and config.team:
        lines.append(f"{config.team}:")
        lines.append(f"GitLab Group Path: {group_title}")
        if config.group_url:
            lines.append(f"GitLab Group URL : [{config.group_path} · GitLab]({config.group_url})")
        lines.append("")
    else:
        lines.append(group_title)
        lines.append("")
    if config and config.development_branches:
        lines.append("## Development Branch List")
        lines.append("")
        lines.append("| No. | Branch Name | Note |")
        lines.append("| --- | ----------- | ---- |")
        for idx, item in enumerate(config.development_branches, start=1):
            branch_name = item.get("branch", "")
            note = item.get("note", "")
            lines.append(f"| {idx} | {branch_name} | {note} |")
        lines.append("")
        if config.branch_naming_rule:
            lines.append("branch name rule:")
            for rule_line in config.branch_naming_rule.strip().splitlines():
                lines.append(rule_line)
            lines.append("")
    lines.append("")
    lines.append("## Repositories")
    lines.append("")
    grouped: dict[str, list[ProjectActivity]] = {}
    for project in projects:
        grouped.setdefault(project.relative_path, []).append(project)
    for rel_path in sorted(grouped.keys(), key=project_sort_key):
        lines.append(f"### {rel_path}")
        lines.append("")
        for activity in grouped[rel_path]:
            lines.append("")
            lines.append("| No. | Year | Week | Date | Commit | Link | Tag | Breif |")
            lines.append("| --- | ---- | ---- | ---- | ------ | ---- | --- | ----- |")
            for index, commit in enumerate(activity.commits):
                year = format_year(commit.committed_at, timezone)
                week = format_week_count(commit.committed_at, timezone)
                date = format_short_date(commit.committed_at, timezone)
                title = commit.title.replace("\n", " ").strip()
                commit_id = short_sha(commit.sha)
                tag_str = format_tag_string(commit.tags, configured=False)
                lines.append(
                    f"| {index} | {year} | {week} | {date} | {commit_id} | [link]({commit.web_url}) | {tag_str} | {title} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def make_verify_setting(args: argparse.Namespace) -> str | bool:
    if args.insecure:
        return False
    if args.ca_bundle:
        return args.ca_bundle
    return True


def load_token() -> str:
    token = os.environ.get("GITLAB_TOKEN", "").strip()
    if not token:
        raise GitLabReporterError("GITLAB_TOKEN is required in the environment")
    return token


def write_output(markdown: str, output_path: str, *, also_stdout: bool) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    print(f"wrote Markdown report: {output_path}", file=sys.stderr)
    if also_stdout:
        sys.stdout.write(markdown)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config_path)
    args.base_url = config.base_url
    args.group = config.group
    args.branches = list(config.branches)
    args.since = config.since
    args.until = config.until
    args.timezone = config.timezone or "Asia/Taipei"
    validate_required_args(args, require_branches=not bool(config.repositories))
    token = load_token()
    timezone = ZoneInfo(args.timezone)
    client = GitLabClient(args.base_url, token, verify=make_verify_setting(args))
    if config.repositories:
        group_title = f"{config.group_path} Group" if config.group_path else f"{args.group} Group"
        projects = collect_configured_activity(client, config=config, stderr=sys.stderr)
        markdown = render_markdown(group_title, projects, timezone, config=config, configured=True)
    else:
        since = parse_user_datetime(args.since, end_of_day=False)
        until = parse_user_datetime(args.until, end_of_day=True)
        if since > until:
            raise GitLabReporterError("--since must be earlier than or equal to --until")
        group_title, projects = collect_activity(
            client,
            group=args.group,
            branches=args.branches,
            since=since,
            until=until,
            stderr=sys.stderr,
        )
        markdown = render_markdown(group_title, projects, timezone, config=config)
    output_path = args.output or default_output_path()
    write_output(markdown, output_path, also_stdout=args.stdout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GitLabReporterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
