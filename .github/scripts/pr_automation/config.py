#!/usr/bin/env python3
"""
Configuration Management for DRS PR Automation

Handles all configuration loading and path resolution.
"""

import os
from pathlib import Path

from ruamel.yaml import YAML, YAMLError


class AutomationConfig:
    """Handles all configuration loading and path resolution."""

    def __init__(self):
        self.repo_root = self._find_repo_root()

    def _find_repo_root(self) -> Path:
        """Find repository root using GitHub Actions workspace or current directory."""
        return Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd()))

    def _load_repositories_config(self) -> list:
        """Load raw repository entries from config file."""
        config_file = Path(f"{self.repo_root}/.github/config/repositories.yaml")
        if not config_file.exists():
            print("Warning: No repository configuration found, no repos will be processed")
            return []
        try:
            yaml = YAML(typ="safe", pure=True)
            with open(config_file) as f:
                config = yaml.load(f) or {}
        except YAMLError as e:
            print(f"Warning: Malformed repositories.yaml, no repos will be processed: {e}")
            return []
        return config.get("included_repositories") or []

    def load_inclusions(self) -> set[str]:
        """Load repository inclusion configuration for phased rollout."""
        try:
            entries = self._load_repositories_config()
            result = set()
            for entry in entries:
                if isinstance(entry, str):
                    result.add(entry)
                elif isinstance(entry, dict) and "repo" in entry:
                    result.add(entry["repo"])
            return result
        except (OSError, ValueError) as e:
            print(f"Warning: Could not load repository configuration: {e}")
            return set()

    def load_repo_configs(self) -> dict[str, dict]:
        """Load per-repo workflow config (e.g. operator-path) from repositories.yaml.

        Returns a dict mapping repo full names to their config overrides.
        Plain string entries get empty config.
        """
        try:
            entries = self._load_repositories_config()
            configs = {}
            for entry in entries:
                if isinstance(entry, str):
                    configs[entry] = {}
                elif isinstance(entry, dict) and "repo" in entry:
                    repo_name = entry["repo"]
                    overrides = {k: v for k, v in entry.items() if k != "repo"}
                    configs[repo_name] = overrides
            return configs
        except (OSError, ValueError) as e:
            print(f"Warning: Could not load repository configuration: {e}")
            return {}

    def get_workflow_template_path(self) -> Path:
        """Get path to workflow template."""
        return Path(f"{self.repo_root}/.github/templates/workflow.yml")
