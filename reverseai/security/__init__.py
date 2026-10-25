"""Security primitives: input validation, process limits, and capability policy."""

from .approvals import Approval, ApprovalError, ApprovalLedger
from .capabilities import CapabilityDenied, CapabilityPolicy
from .gate import ActionGate, GateDecision, GateError
from .limits import ResourceLimits
from .vault import Vault, VaultError, VaultUnavailable
from .validate import (
    MAX_FILE_BYTES,
    ValidationError,
    contains_path,
    read_target,
    safe_join,
    validate_file_size,
)

__all__ = [
    "CapabilityDenied",
    "CapabilityPolicy",
    "Approval",
    "ApprovalError",
    "ApprovalLedger",
    "ActionGate",
    "GateDecision",
    "GateError",
    "Vault",
    "VaultError",
    "VaultUnavailable",
    "ResourceLimits",
    "MAX_FILE_BYTES",
    "ValidationError",
    "contains_path",
    "read_target",
    "safe_join",
    "validate_file_size",
]
