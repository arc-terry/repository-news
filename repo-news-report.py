#!/usr/bin/env python3
from repo_news_report import GitLabReporterError, main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GitLabReporterError as exc:
        import sys

        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
