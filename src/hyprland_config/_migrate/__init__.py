"""Deprecation checking and migration transforms for Hyprland configs.

Submodules:

- :mod:`._deprecations` — declarative ``_DeprecationRule`` table plus the
  read-only :func:`check_deprecated` reporter.
- :mod:`._windowrule` — Hyprland 0.48/0.53 windowrule v1↔v2↔v3 transforms.
  Cordoned off because they're regex-heavy and account for most of the
  cognitive load in the migration layer.
- :mod:`._runner` — :func:`migrate` orchestrator plus the migrations
  list and the shared line-rewrite helpers.
"""

from hyprland_config._migrate._deprecations import (
    ConfigDeprecation,
    check_deprecated,
)
from hyprland_config._migrate._runner import MigrationResult, migrate
from hyprland_config._migrate._windowrule import normalize_rules

__all__ = [
    "ConfigDeprecation",
    "MigrationResult",
    "check_deprecated",
    "migrate",
    "normalize_rules",
]
