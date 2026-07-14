"""Synthetic-only, deterministic judgment-reasoning policy experiment."""

__all__ = [
    "POLICY_IDS",
    "assert_redacted_output",
    "commit_state_if_valid",
    "frozen_manifest",
    "isolated_database_path",
    "run_experiment",
    "verify_independent_transfer",
]


def __getattr__(name: str):
    """Load the runner on demand so ``python -m`` stays warning-free."""

    if name in __all__:
        from . import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
