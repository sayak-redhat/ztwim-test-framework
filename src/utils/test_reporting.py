"""
Test reporting utilities for pytest hooks.

This module applies a small facade pattern around report setup/finalization so
`conftest.py` stays focused on fixtures and test behavior.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ReportContext:
    """Holds computed paths for a single pytest run."""

    timestamp: str
    base_report_dir: str
    run_report_dir: str
    report_path: str
    latest_symlink: str


class ReportManager:
    """Facade for report directory lifecycle."""

    def __init__(self, workspace_dir: str, keep_latest: int = 5):
        self.workspace_dir = workspace_dir
        self.keep_latest = keep_latest

    def configure(self, config) -> ReportContext:
        """Compute report paths and attach them to pytest config."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_report_dir = os.path.join(self.workspace_dir, "test-reports")
        run_report_dir = os.path.join(base_report_dir, timestamp)
        report_path = os.path.join(run_report_dir, "test-report.html")
        latest_symlink = os.path.join(base_report_dir, "latest")

        os.makedirs(run_report_dir, exist_ok=True)

        config.option.htmlpath = report_path
        css_path = os.path.join(self.workspace_dir, "assets", "pytest-html-style.css")
        if os.path.exists(css_path):
            config.option.css = [css_path]

        config._report_timestamp = timestamp
        config._run_report_dir = run_report_dir
        config._base_report_dir = base_report_dir

        self._update_latest_symlink(latest_symlink, timestamp)
        self._prune_old_reports(base_report_dir)

        logger.info("")
        logger.info(f"📁 Report directory: {run_report_dir}")
        logger.info("   ├── test-report.html")
        logger.info("")

        return ReportContext(
            timestamp=timestamp,
            base_report_dir=base_report_dir,
            run_report_dir=run_report_dir,
            report_path=report_path,
            latest_symlink=latest_symlink,
        )

    def finalize(self, config) -> None:
        """Finalize report metadata and print a concise summary."""
        run_report_dir = getattr(config, "_run_report_dir", None)
        base_report_dir = getattr(config, "_base_report_dir", None)
        if not run_report_dir or not base_report_dir:
            return

        latest_link = os.path.join(base_report_dir, "latest")
        run_dir_name = os.path.basename(run_report_dir)
        self._update_latest_symlink(latest_link, run_dir_name)

        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 TEST REPORTS GENERATED")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"📁 {run_report_dir}/")
        logger.info("   └── test-report.html ← Test results (pass/fail) with logs")
        logger.info("")
        logger.info(f"🔗 Quick access: {latest_link}/test-report.html")
        logger.info("=" * 60)

    def _update_latest_symlink(self, latest_symlink: str, target: str) -> None:
        """Create or refresh the latest symlink."""
        try:
            if os.path.islink(latest_symlink):
                os.unlink(latest_symlink)
            elif os.path.exists(latest_symlink):
                os.remove(latest_symlink)
            os.symlink(target, latest_symlink, target_is_directory=True)
        except OSError:
            logger.debug("Could not create/update latest symlink")

    def _prune_old_reports(self, base_report_dir: str) -> None:
        """Keep only most recent report directories."""
        try:
            entries = []
            for name in os.listdir(base_report_dir):
                path = os.path.join(base_report_dir, name)
                if name == "latest" or os.path.islink(path) or not os.path.isdir(path):
                    continue
                try:
                    datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
                    entries.append(name)
                except ValueError:
                    continue

            entries.sort(reverse=True)
            if len(entries) <= self.keep_latest:
                return

            for old_name in entries[self.keep_latest :]:
                shutil.rmtree(os.path.join(base_report_dir, old_name), ignore_errors=True)
            logger.info(
                f"🧹 Cleaned up {len(entries[self.keep_latest:])} old report(s), "
                f"keeping latest {self.keep_latest}"
            )
        except Exception as exc:  # best effort
            logger.debug(f"Could not cleanup old reports: {exc}")
