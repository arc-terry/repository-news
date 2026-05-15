from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

from gitlab_branch_news import (
    BranchConfig,
    CommitEntry,
    GitLabClient,
    ProjectActivity,
    ReportConfig,
    RepositoryConfig,
    build_tag_map,
    collect_activity,
    collect_configured_activity,
    default_output_path,
    format_report_date,
    format_short_date,
    format_week_count,
    load_config,
    merge_config_and_args,
    parse_args,
    parse_user_datetime,
    project_relative_path,
    render_markdown,
    validate_required_args,
    write_output,
)


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, verify=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "verify": verify, "timeout": timeout})
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses.pop(0)


class FormattingTests(unittest.TestCase):
    def test_parse_user_datetime_supports_day_bounds(self):
        self.assertEqual(
            parse_user_datetime("2026-05-05", end_of_day=False),
            datetime(2026, 5, 5, 0, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            parse_user_datetime("2026-05-05", end_of_day=True),
            datetime(2026, 5, 5, 23, 59, 59, tzinfo=UTC),
        )

    def test_week_and_date_use_timezone(self):
        committed_at = datetime.fromisoformat("2026-05-05T23:30:00+00:00")
        timezone = ZoneInfo("Asia/Taipei")
        self.assertEqual(format_report_date(committed_at, timezone), "05062026")
        self.assertEqual(format_week_count(committed_at, timezone), "W19")
        self.assertEqual(format_short_date(committed_at, timezone), "0506")

    def test_relative_path_strips_group_prefix(self):
        project = {"path_with_namespace": "kpn/v16-compact/guangzhou_gitlab_mirror/feeds/sah/feed_arcadyan"}
        self.assertEqual(
            project_relative_path(project, "kpn/v16-compact/guangzhou_gitlab_mirror"),
            "feeds/sah/feed_arcadyan",
        )

    @patch("gitlab_branch_news.datetime")
    def test_default_output_path_uses_current_computer_time(self, datetime_mock):
        datetime_mock.now.return_value = datetime(2026, 5, 15, 17, 31, 45)

        result = default_output_path()

        self.assertEqual(result, "report/2026_W20_0515_173145.md")


class GitLabCollectionTests(unittest.TestCase):
    def test_collect_activity_handles_pagination_and_branch_filtering(self):
        responses = [
            FakeResponse(
                200,
                {
                    "full_name": "KPN/V16 Compact/Guangzhou_GitLab_mirror",
                    "full_path": "kpn/v16-compact/guangzhou_gitlab_mirror",
                },
            ),
            FakeResponse(
                200,
                [
                    {"id": 1, "path": "prplos", "path_with_namespace": "kpn/v16-compact/guangzhou_gitlab_mirror/prplos"},
                    {
                        "id": 2,
                        "path": "feed-qca",
                        "path_with_namespace": "kpn/v16-compact/guangzhou_gitlab_mirror/feeds/feed-qca",
                    },
                ],
                headers={"X-Next-Page": "2"},
            ),
            FakeResponse(
                200,
                [
                    {
                        "id": 3,
                        "path": "feed_arcadyan",
                        "path_with_namespace": "kpn/v16-compact/guangzhou_gitlab_mirror/feeds/sah/feed_arcadyan",
                    }
                ],
                headers={},
            ),
            FakeResponse(200, {"name": "arc-hsinchu/kpn-v16-compact"}),
            FakeResponse(
                200,
                [
                    {
                        "id": "b9ec6a1ad5e5bbf18739a5eefbe2c22e2d0d2c47",
                        "title": "profile: kpn_v16_compact update feed_arcadyan",
                        "committed_date": "2026-05-13T03:00:00Z",
                        "web_url": "https://gitlab/prplos/-/commit/b9ec6a1ad5e5bbf18739a5eefbe2c22e2d0d2c47",
                    }
                ],
            ),
            FakeResponse(200, [{"name": "v1.0", "commit": {"id": "b9ec6a1ad5e5bbf18739a5eefbe2c22e2d0d2c47"}}]),
            FakeResponse(404, {"message": "404 Branch Not Found"}),
            FakeResponse(200, {"name": "arc-hsinchu/kpn-v16-compact"}),
            FakeResponse(
                200,
                [
                    {
                        "id": "7e6277a58931ae792f128bab48795083e0f007b7",
                        "title": "feat(silab): add Silicon Labs CPC integration packages",
                        "committed_date": "2026-05-05T07:00:00Z",
                        "web_url": "https://gitlab/feed_arcadyan/-/commit/7e6277a58931ae792f128bab48795083e0f007b7",
                    },
                    {
                        "id": "a4bb9a66229ea3d098c67438e8cafe9a22f1231c",
                        "title": "feat(silab): expose the source code",
                        "committed_date": "2026-05-06T08:00:00Z",
                        "web_url": "https://gitlab/feed_arcadyan/-/commit/a4bb9a66229ea3d098c67438e8cafe9a22f1231c",
                    },
                ],
            ),
            FakeResponse(200, []),
        ]
        session = FakeSession(responses)
        client = GitLabClient("https://gitlab.example.com", "token", verify=False, session=session)
        stderr = io.StringIO()

        title, projects = collect_activity(
            client,
            group="kpn/v16-compact/guangzhou_gitlab_mirror",
            branches=["arc-hsinchu/kpn-v16-compact"],
            since=datetime(2026, 5, 5, 0, 0, tzinfo=UTC),
            until=datetime(2026, 5, 13, 23, 59, tzinfo=UTC),
            stderr=stderr,
        )

        self.assertEqual(title, "KPN/V16 Compact/Guangzhou_GitLab_mirror Group")
        self.assertEqual([project.relative_path for project in projects], ["prplos", "feeds/sah/feed_arcadyan"])
        self.assertIn("warning: branch 'arc-hsinchu/kpn-v16-compact' not found in project 'feeds/feed-qca'", stderr.getvalue())
        self.assertEqual(projects[1].commits[0].sha, "7e6277a58931ae792f128bab48795083e0f007b7")
        group_project_calls = [call for call in session.calls if "/groups/" in call["url"] and "/projects" in call["url"]]
        self.assertEqual(group_project_calls[0]["params"]["page"], 1)
        self.assertEqual(group_project_calls[1]["params"]["page"], 2)

    def test_build_tag_map_creates_sha_to_tags_mapping(self):
        tags = [
            {"name": "v1.0", "commit": {"id": "abc123"}},
            {"name": "v1.1", "commit": {"id": "abc123"}},
            {"name": "v2.0", "commit": {"id": "def456"}},
        ]
        result = build_tag_map(tags)
        self.assertEqual(result["abc123"], ["v1.0", "v1.1"])
        self.assertEqual(result["def456"], ["v2.0"])

    def test_collect_configured_activity_includes_base_commit_and_refs(self):
        responses = [
            FakeResponse(
                200,
                {
                    "id": 10,
                    "path_with_namespace": "kpn/v16-compact/guangzhou_gitlab_mirror/prplos",
                },
            ),
            FakeResponse(200, {"name": "arc-hsinchu/kpn-v16-compact", "commit": {"id": "b9ec6a1a9999"}}),
            FakeResponse(
                200,
                {
                    "id": "2634d9491111",
                    "title": "profile: base commit",
                    "committed_date": "2026-04-29T01:00:00Z",
                    "web_url": "https://gitlab/prplos/-/commit/2634d9491111",
                },
            ),
            FakeResponse(
                200,
                {
                    "commits": [
                        {
                            "id": "9afbd00d2222",
                            "title": "profile: next commit",
                            "committed_date": "2026-05-06T02:00:00Z",
                            "web_url": "https://gitlab/prplos/-/commit/9afbd00d2222",
                        },
                        {
                            "id": "b9ec6a1a9999",
                            "title": "profile: tip commit",
                            "committed_date": "2026-05-13T03:00:00Z",
                            "web_url": "https://gitlab/prplos/-/commit/b9ec6a1a9999",
                        },
                    ]
                },
            ),
            FakeResponse(200, [{"name": "v1.0", "commit": {"id": "b9ec6a1a9999"}}]),
            FakeResponse(200, [{"name": "sah/kpn-v16-compact", "type": "branch"}]),
            FakeResponse(200, []),
            FakeResponse(200, [{"name": "arc-hsinchu/kpn-v16-compact", "type": "branch"}]),
        ]
        session = FakeSession(responses)
        client = GitLabClient("https://gitlab.example.com", "token", verify=False, session=session)
        config = ReportConfig(
            group="kpn/v16-compact/guangzhou_gitlab_mirror",
            repositories=(
                RepositoryConfig(
                    path="prplos",
                    branches=(BranchConfig(name="arc-hsinchu/kpn-v16-compact", base_commit="2634d949"),),
                ),
            ),
        )

        projects = collect_configured_activity(client, config=config, stderr=io.StringIO())

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].relative_path, "prplos")
        self.assertEqual(projects[0].base_commit, "2634d949")
        self.assertEqual([commit.sha for commit in projects[0].commits], ["2634d9491111", "9afbd00d2222", "b9ec6a1a9999"])
        self.assertEqual(projects[0].commits[0].branch, "sah/kpn-v16-compact")
        self.assertEqual(projects[0].commits[1].branch, "-")
        self.assertEqual(projects[0].commits[2].tags, ("v1.0",))


class MarkdownRenderTests(unittest.TestCase):
    def test_render_markdown_matches_expected_shape(self):
        activity = [
            ProjectActivity(
                relative_path="prplos",
                branch="arc-hsinchu/kpn-v16-compact",
                commits=(
                    CommitEntry(
                        sha="9afbd00df86cde8dab9f01524868efcfbc0b2239",
                        title="profile: kpn_v16_compact replaces upstream git server url for hsinchu development",
                        committed_at=datetime.fromisoformat("2026-05-05T17:30:00+00:00"),
                        web_url="https://gitlab/prplos/-/commit/9afbd00df86cde8dab9f01524868efcfbc0b2239",
                        branch="arc-hsinchu/kpn-v16-compact",
                        tags=("v1.0",),
                    ),
                ),
            )
        ]

        rendered = render_markdown(
            "KPN/V16 Compact/Guangzhou_GitLab_mirror Group",
            activity,
            ZoneInfo("Asia/Taipei"),
        )

        self.assertIn("```table-of-contents", rendered)
        self.assertIn("## Overview", rendered)
        self.assertIn("## Repositories", rendered)
        self.assertIn("### prplos", rendered)
        self.assertNotIn("| Branch |", rendered)
        self.assertIn("| 0 | 2026 | W19 | 0506 | 9afbd00d | [link](https://gitlab/prplos/-/commit/9afbd00df86cde8dab9f01524868efcfbc0b2239) | v1.0 | profile: kpn_v16_compact replaces upstream git server url for hsinchu development |", rendered)

    @patch("gitlab_branch_news.datetime")
    def test_render_markdown_matches_configured_expected_shape(self, datetime_mock):
        datetime_mock.now.return_value = datetime(2026, 5, 14, 9, 31, tzinfo=UTC)
        datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
        activity = [
            ProjectActivity(
                relative_path="prplos",
                branch="arc-hsinchu/kpn-v16-compact",
                base_commit="2634d949",
                commits=(
                    CommitEntry(
                        sha="2634d949c90acdfa6b77673591db27289fc384b4",
                        title="profile: kpn_v16_compact update feed_qca commit to fix bugs",
                        committed_at=datetime.fromisoformat("2026-04-29T01:00:00+00:00"),
                        web_url="https://gitlab/prplos/-/commit/2634d949c90acdfa6b77673591db27289fc384b4",
                        branch="sah/kpn-v16-compact",
                    ),
                    CommitEntry(
                        sha="b9ec6a1ad5e5bbf18739a5eefbe2c22e2d0d2c47",
                        title="profile: kpn_v16_compact update feed_arcadyan",
                        committed_at=datetime.fromisoformat("2026-05-13T03:00:00+00:00"),
                        web_url="https://gitlab/prplos/-/commit/b9ec6a1ad5e5bbf18739a5eefbe2c22e2d0d2c47",
                        branch="arc-hsinchu/kpn-v16-compact",
                    ),
                ),
            ),
            ProjectActivity(
                relative_path="prplos",
                branch="arc-hsinchu/dev-kpn-v16-compact_2026.05.15",
                base_commit="c4b31665",
                commits=(
                    CommitEntry(
                        sha="c4b31665e3ed17a380b97b1b0cc3615098396506",
                        title="profile: kpn_v16_compact update feed_arcadyan",
                        committed_at=datetime.fromisoformat("2026-05-13T05:00:00+00:00"),
                        web_url="https://gitlab/prplos/-/commit/c4b31665e3ed17a380b97b1b0cc3615098396506",
                        branch="arc-hsinchu/dev-kpn-v16-compact_2026.05.15",
                    ),
                ),
            ),
        ]
        config = ReportConfig(
            team="Hsinchu Team",
            group_path="KPN/V16 Compact/Guangzhou_GitLab_mirror",
            group_url="https://vcs-sw2.arcadyan.com.tw/kpn/v16-compact/guangzhou_gitlab_mirror",
        )

        rendered = render_markdown(
            "KPN/V16 Compact/Guangzhou_GitLab_mirror Group",
            activity,
            ZoneInfo("Asia/Taipei"),
            config=config,
            configured=True,
        )

        self.assertNotIn("```table-of-contents", rendered)
        self.assertIn("Sync. Date: 05142026 PM 05:31", rendered)
        self.assertIn("| GitLab Group Path | KPN/V16 Compact/Guangzhou_GitLab_mirror Group |", rendered)
        self.assertIn("| GitLab Group URL  | [Guangzhou_GitLab_mirror · GitLab](https://vcs-sw2.arcadyan.com.tw/kpn/v16-compact/guangzhou_gitlab_mirror) |", rendered)
        self.assertIn("| No. | Base Commit | Branch Name |", rendered)
        self.assertIn("| 1   | 2634d949    | arc-hsinchu/kpn-v16-compact |", rendered)
        self.assertIn("#### arc-hsinchu/kpn-v16-compact", rendered)
        self.assertNotIn("| Branch |", rendered)
        self.assertIn("| 0   | 2026 | W18  | 0429 | 2634d949 | [link](https://gitlab/prplos/-/commit/2634d949c90acdfa6b77673591db27289fc384b4) | -   | profile: kpn_v16_compact update feed_qca commit to fix bugs |", rendered)
        self.assertIn("#### arc-hsinchu/dev-kpn-v16-compact_2026.05.15", rendered)

    def test_write_output_creates_markdown_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "report.md")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                write_output("# Report\n", output_path, also_stdout=False)

            with open(output_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "# Report\n")
            self.assertIn("wrote Markdown report:", stderr.getvalue())

    def test_write_output_creates_report_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "report", "test.md")
            with patch("sys.stderr", new_callable=io.StringIO):
                write_output("# Report\n", output_path, also_stdout=False)
            self.assertTrue(os.path.exists(output_path))


class MainFlowTests(unittest.TestCase):
    @patch("gitlab_branch_news.load_token", return_value="token")
    @patch("gitlab_branch_news.default_output_path", return_value="report/current-time.md")
    @patch("gitlab_branch_news.collect_activity")
    @patch("gitlab_branch_news.write_output")
    @patch("gitlab_branch_news.GitLabClient")
    def test_main_builds_client_with_ca_bundle(
        self,
        client_cls,
        write_output_mock,
        collect_activity_mock,
        default_output_path_mock,
        _load_token,
    ):
        from gitlab_branch_news import main

        collect_activity_mock.return_value = ("Group Name Group", [])
        exit_code = main(
            [
                "--base-url",
                "https://gitlab.example.com",
                "--group",
                "my-group",
                "--branch",
                "feature/test",
                "--since",
                "2026-05-01",
                "--until",
                "2026-05-31",
                "--ca-bundle",
                "/tmp/ca.pem",
            ]
        )

        self.assertEqual(exit_code, 0)
        client_cls.assert_called_once_with("https://gitlab.example.com", "token", verify="/tmp/ca.pem")
        default_output_path_mock.assert_called_once_with()
        write_output_mock.assert_called_once()
        self.assertEqual(
            write_output_mock.call_args.args[1],
            "report/current-time.md",
        )
        self.assertFalse(write_output_mock.call_args.kwargs["also_stdout"])

    @patch("gitlab_branch_news.load_token", return_value="token")
    @patch("gitlab_branch_news.collect_activity")
    @patch("gitlab_branch_news.write_output")
    @patch("gitlab_branch_news.GitLabClient")
    def test_main_passes_multiple_branches(self, client_cls, write_output_mock, collect_activity_mock, _load_token):
        from gitlab_branch_news import main

        collect_activity_mock.return_value = ("Group Name Group", [])
        main(
            [
                "--base-url",
                "https://gitlab.example.com",
                "--group",
                "my-group",
                "--branch",
                "feature/test",
                "--branch",
                "feature/test2",
                "--since",
                "2026-05-01",
                "--until",
                "2026-05-31",
            ]
        )

        call_kwargs = collect_activity_mock.call_args.kwargs
        self.assertEqual(call_kwargs["branches"], ["feature/test", "feature/test2"])


class ConfigFirstTests(unittest.TestCase):
    def test_load_config_extracts_cli_settings(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "base_url": "https://gitlab.config.com",
                "group": "config-group",
                "branches": ["main", "develop"],
                "since": "2026-01-01",
                "until": "2026-01-31",
                "timezone": "UTC",
            }, f)
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config.base_url, "https://gitlab.config.com")
        self.assertEqual(config.group, "config-group")
        self.assertEqual(config.branches, ("main", "develop"))
        self.assertEqual(config.since, "2026-01-01")
        self.assertEqual(config.until, "2026-01-31")
        self.assertEqual(config.timezone, "UTC")

    def test_load_config_extracts_repositories(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "base_url": "https://gitlab.config.com",
                "group": "config-group",
                "since": "2026-01-01",
                "until": "2026-01-31",
                "repositories": [
                    {
                        "path": "prplos",
                        "branches": [
                            {"name": "arc-hsinchu/kpn-v16-compact", "base_commit": "2634d949"},
                            {"name": "arc-hsinchu/dev-kpn-v16-compact_2026.05.15", "base_commit": "c4b31665"},
                        ],
                    }
                ],
            }, f)
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config.repositories[0].path, "prplos")
        self.assertEqual(config.repositories[0].branches[0], BranchConfig("arc-hsinchu/kpn-v16-compact", "2634d949"))
        self.assertEqual(
            config.repositories[0].branches[1],
            BranchConfig("arc-hsinchu/dev-kpn-v16-compact_2026.05.15", "c4b31665"),
        )

    def test_cli_args_override_config_values(self):
        config = ReportConfig(
            base_url="https://config.example.com",
            group="config-group",
            branches=("config-branch",),
            since="2026-01-01",
            until="2026-01-31",
            timezone="UTC",
        )
        args = parse_args([
            "--base-url", "https://cli.example.com",
            "--group", "cli-group",
        ])
        merged = merge_config_and_args(config, args)
        self.assertEqual(merged.base_url, "https://cli.example.com")
        self.assertEqual(merged.group, "cli-group")
        self.assertEqual(merged.branches, ["config-branch"])
        self.assertEqual(merged.since, "2026-01-01")
        self.assertEqual(merged.until, "2026-01-31")

    def test_config_values_used_when_cli_args_missing(self):
        config = ReportConfig(
            base_url="https://config.example.com",
            group="config-group",
            branches=("config-branch",),
            since="2026-01-01",
            until="2026-01-31",
            timezone="Europe/London",
        )
        args = parse_args([])
        merged = merge_config_and_args(config, args)
        self.assertEqual(merged.base_url, "https://config.example.com")
        self.assertEqual(merged.group, "config-group")
        self.assertEqual(merged.branches, ["config-branch"])
        self.assertEqual(merged.timezone, "Europe/London")

    def test_validate_required_args_raises_for_missing(self):
        args = parse_args([])
        with self.assertRaises(Exception) as ctx:
            validate_required_args(args)
        self.assertIn("--base-url", str(ctx.exception))
        self.assertIn("--group", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
