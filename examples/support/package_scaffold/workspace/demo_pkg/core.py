"""Core package tools for the package scaffolding example."""

from __future__ import annotations


def solve(mesh_size: int = 2) -> int:
    """Solve a deterministic case.

    :param mesh_size: Mesh size.
    :returns: Scaled score.
    """
    return mesh_size * 3


class CounterSession:
    """Maintain a tiny mutable counter.

    :param start: Starting count.
    """

    def __init__(self, start: int = 0) -> None:
        """Initialize the counter session."""
        self.value = start

    def increment(self, amount: int = 1) -> int:
        """Increment the counter.

        :param amount: Increment amount.
        :returns: Updated count.
        """
        self.value += amount
        return self.value

    def close(self) -> None:
        """Close the session."""
        self.value = -1
