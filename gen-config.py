#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    yaml = None


def parse_repo_branch(value: str) -> tuple[str, str, str]:
    if ":" not in value or "=" not in value:
        raise argparse.ArgumentTypeError("expected REPO_PATH:BRANCH_NAME=BASE_REF")
    repo_path, branch_and_commit = value.split(":", 1)
    branch_name, base_ref = branch_and_commit.rsplit("=", 1)
    repo_path = repo_path.strip("/")
    branch_name = branch_name.strip()
    base_ref = base_ref.strip()
    if not repo_path or not branch_name or not base_ref:
        raise argparse.ArgumentTypeError("repo path, branch name, and base ref are required")
    return repo_path, branch_name, base_ref


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a YAML config for repo-news-report.py.")
    parser.add_argument("--output", required=True, help="Path to write the generated YAML config.")
    parser.add_argument("--base-url", required=True, help="GitLab base URL, e.g. https://gitlab.example.com")
    parser.add_argument("--group", required=True, help="GitLab group path.")
    parser.add_argument("--since", help="Optional start date or timestamp.")
    parser.add_argument("--until", help="Optional end date or timestamp.")
    parser.add_argument("--timezone", default="Asia/Taipei", help="IANA timezone, default: Asia/Taipei.")
    parser.add_argument("--team", default="", help="Team label for the report overview.")
    parser.add_argument("--group-path", default="", help="Display name for the GitLab group.")
    parser.add_argument("--group-url", default="", help="GitLab group URL for the report overview.")
    parser.add_argument(
        "--repo-branch",
        action="append",
        type=parse_repo_branch,
        required=True,
        metavar="REPO_PATH:BRANCH_NAME=BASE_REF",
        help="Repository branch entry. Repeat this option for each branch.",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> dict:
    repositories: dict[str, list[dict[str, str]]] = {}
    for repo_path, branch_name, base_ref in args.repo_branch:
        repositories.setdefault(repo_path, []).append({"name": branch_name, "base_ref": base_ref})

    config = {
        "base_url": args.base_url,
        "group": args.group,
        "timezone": args.timezone,
    }
    if args.since:
        config["since"] = args.since
    if args.until:
        config["until"] = args.until
    overview = {}
    if args.team:
        overview["team"] = args.team
    if args.group_path:
        overview["group_path"] = args.group_path
    if args.group_url:
        overview["group_url"] = args.group_url
    if overview:
        config["overview"] = overview
    config["repositories"] = [
        {"path": repo_path, "branches": branches}
        for repo_path, branches in repositories.items()
    ]
    return config


def write_config(config: dict, output_path: str) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write YAML config files (pip install pyyaml)")
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=False)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write_config(build_config(args), args.output)
    print(f"wrote YAML config: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
