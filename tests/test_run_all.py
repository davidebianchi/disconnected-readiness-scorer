"""Tests proving run_all.py's direct call to main._run() inherits config fail-hard behavior.

run_all.py bypasses main()'s CLI dispatch and its try/except entirely -- it builds its
own SimpleNamespace and calls _run() directly (see run_all.py's process_repo()). These
tests replicate that exact call shape to prove the ValueError raised by a missing
--config path still propagates out of _run() the same way it does through main()'s own
dispatch -- see RHOAIENG-79773.
"""

import io
from types import SimpleNamespace

import pytest

from main import _run


def _run_all_style_args(repo_root, config_path):
    """Mirror run_all.py's process_repo() SimpleNamespace construction exactly."""
    return SimpleNamespace(
        repo_root=str(repo_root),
        rules="all",
        report="json,markdown",
        output=[str(repo_root / "report.json"), str(repo_root / "report.md")],
        operator_path=None,
        config=config_path,
        repo_config=None,
        no_production_scope=False,
        verbose=False,
        arch_analyzer="",
    )


class TestRunAllConfigFailHard:
    def test_missing_config_path_raises_through_run_all_call_shape(self, tmp_path):
        args = _run_all_style_args(tmp_path, str(tmp_path / "nope.yaml"))

        with pytest.raises(ValueError, match="Config file not found"):
            _run(
                args,
                None,
                manifest=None,
                manifest_env_vars=None,
                operator_arch_data=None,
                log_stream=io.StringIO(),
            )
