"""Verification — prove (or disprove) that a modification did what was intended
without breaking what worked, by comparing behavior in the sandbox.
"""

from .regression import VerificationReport, compare_execution

__all__ = ["VerificationReport", "compare_execution"]
