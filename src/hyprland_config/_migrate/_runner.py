"""Migration orchestrator: the :func:`migrate` entry point and the
``_MIGRATIONS`` table that drives it.

Houses the migration factories for one-shot renames/moves/deletes that
don't need their own function. Per-version transforms with more meat
live in :mod:`._windowrule`.

Notable: ``BLUR_OPTIONS`` lives here because the blur-subsection
migration is its primary consumer; :mod:`._deprecations` imports it
to derive matching warning rules.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from hyprland_config._core._model import Document, KeyValueLine
from hyprland_config._core._types import parse_version
from hyprland_config._migrate._helpers import transform_lines
from hyprland_config._migrate._windowrule import (
    migrate_windowrule_v1_to_v2,
    migrate_windowrule_v2_to_v3,
    normalize_rules,
)

# Blur options that moved from decoration:blur_* to decoration:blur:* in v0.40.
BLUR_OPTIONS = ("size", "passes", "new_optimizations", "ignore_opacity")


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changes_made(self) -> bool:
        return bool(self.applied)


@dataclass
class _Migration:
    description: str
    from_version: str
    to_version: str
    transform: Callable[[Document], bool]

    @cached_property
    def from_ver(self) -> tuple[int, ...]:
        return parse_version(self.from_version)


def _rewrite_line_key(line: KeyValueLine, new_full_key: str) -> None:
    """Rewrite ``line`` to use ``new_full_key``, preserving flat-vs-sectioned syntax.

    The parser exposes two shapes:

    - Flat colon syntax (e.g. ``decoration:blur:size = 8`` at top level):
      ``line.key == line.full_key`` — the whole colon path is written inline.
    - Sectioned syntax (inside ``decoration { blur { size = 8 } }``):
      ``line.key`` is the leaf ``size`` while ``line.full_key`` is the full path.

    Migrations must preserve whichever shape the line already has — otherwise
    a flat ``decoration:blur_size = 8`` line rewrites as ``size = 8``, losing
    its section context.
    """
    is_flat = line.key == line.full_key
    line.full_key = new_full_key
    new_leaf = new_full_key.rsplit(":", 1)[-1]
    line.key = new_full_key if is_flat else new_leaf
    line.update_raw()


def _migrate_blur_options(doc: Document) -> bool:
    """Move decoration:blur_* options to decoration:blur:* subsection."""
    renames = {f"decoration:blur_{opt}": f"decoration:blur:{opt}" for opt in BLUR_OPTIONS}

    def transform(line: KeyValueLine) -> None:
        _rewrite_line_key(line, renames[line.full_key])

    return transform_lines(doc, lambda ln: ln.full_key in renames, transform)


def _make_rename_migration(
    old_full_key: str,
    new_full_key: str,
    *,
    match_by: Literal["full_key", "key"] = "full_key",
) -> Callable[[Document], bool]:
    """Build a migration that renames a key.

    *match_by* controls how lines are matched:
    - ``"full_key"`` (default): match on ``line.full_key == old_full_key``
    - ``"key"``: match on ``line.key == old_full_key`` (for top-level keywords)
    """

    def transform(line: KeyValueLine) -> None:
        # Rewrite the full_key via substring replacement so callers can pass
        # partial paths (e.g. the "key" match_by case) and still land on the
        # right target; then resync the raw form via _rewrite_line_key, which
        # preserves flat-colon vs. sectioned syntax.
        replaced_full_key = line.full_key.replace(old_full_key, new_full_key, 1)
        _rewrite_line_key(line, replaced_full_key)

    if match_by == "key":
        old_leaf = old_full_key.rsplit(":", 1)[-1]
        return lambda doc: transform_lines(doc, lambda ln: ln.key == old_leaf, transform)
    return lambda doc: transform_lines(doc, lambda ln: ln.full_key == old_full_key, transform)


def _make_delete_migration(full_key: str) -> Callable[[Document], bool]:
    """Build a migration that removes all lines matching ``full_key``.

    Used for options that were removed with no replacement (e.g.
    ``dwindle:pseudotile`` and ``render:cm_fs_passthrough`` in v0.55).
    Matches both flat colon syntax and sectioned forms, since both
    resolve to the same ``full_key``.
    """

    def migration(doc: Document) -> bool:
        before = len(doc.lines)
        doc.remove_matching_lines(
            lambda ln: isinstance(ln, KeyValueLine) and ln.full_key == full_key
        )
        return len(doc.lines) != before

    return migration


def _make_move_migration(old_full_key: str, new_full_key: str) -> Callable[[Document], bool]:
    """Build a migration that moves a key to a different section path.

    Handles both forms the parser produces:

    - **Flat colon syntax** (``misc:vfr = false``): renamed in place via
      :func:`_rewrite_line_key`, same as a regular rename.
    - **Sectioned syntax** (inside ``misc { vfr = false }``): the line is
      physically removed from its current section and re-inserted into
      the target section using :meth:`Document.insert_assignment`,
      which creates the target section if it doesn't already exist.
      Inline comments on the original line are forwarded to the new line.

    A plain rename via :func:`_rewrite_line_key` is wrong for the sectioned
    case because it only rewrites ``full_key`` and the leaf — the line
    stays inside the original section block, and Hyprland re-parses it
    under the original section prefix.
    """

    def migration(doc: Document) -> bool:
        targets = [
            ln for ln in doc.lines if isinstance(ln, KeyValueLine) and ln.full_key == old_full_key
        ]
        if not targets:
            return False

        for line in targets:
            if line.key == line.full_key:
                _rewrite_line_key(line, new_full_key)
            else:
                value = line.value
                inline_comment = line.inline_comment
                doc.lines = [ln for ln in doc.lines if ln is not line]
                doc.insert_assignment(new_full_key, value, inline_comment=inline_comment)

        doc.mark_dirty()
        return True

    return migration


_LAYOUTMSG_DISPATCHERS = frozenset({"togglesplit", "swapsplit", "splitratio"})


def _migrate_dispatchers_to_layoutmsg(doc: Document) -> bool:
    """Rewrite ``bind = …, togglesplit`` → ``bind = …, layoutmsg, togglesplit``.

    Hyprland 0.55 moved ``togglesplit``, ``swapsplit``, and ``splitratio``
    from standalone dispatchers to ``layoutmsg`` subcommands.
    """

    def predicate(line: KeyValueLine) -> bool:
        if not line.key.startswith("bind"):
            return False
        parts = line.value.split(",", 3)
        return len(parts) >= 3 and parts[2].strip() in _LAYOUTMSG_DISPATCHERS

    def transform(line: KeyValueLine) -> None:
        parts = line.value.split(",", 3)
        old_dispatcher = parts[2].strip()
        old_args = parts[3].strip() if len(parts) > 3 else ""
        layoutmsg_args = f"{old_dispatcher} {old_args}".strip()
        parts[2] = " layoutmsg"
        parts[3:] = [f" {layoutmsg_args}"]
        line.value = ",".join(parts)
        line.update_raw()

    return transform_lines(doc, predicate, transform)


_MIGRATIONS: list[_Migration] = sorted(
    [
        _Migration(
            "Rename exec_once → exec-once",
            "0.33",
            "0.34",
            _make_rename_migration("exec_once", "exec-once", match_by="key"),
        ),
        _Migration(
            "Move blur options to decoration:blur subsection",
            "0.39",
            "0.40",
            _migrate_blur_options,
        ),
        _Migration(
            "Rename no_cursor_warps → no_warps",
            "0.40",
            "0.41",
            _make_rename_migration("cursor:no_cursor_warps", "cursor:no_warps"),
        ),
        _Migration(
            "Move sensitivity from general to input",
            "0.39",
            "0.40",
            _make_rename_migration("general:sensitivity", "input:sensitivity"),
        ),
        _Migration(
            "Convert windowrule v1 → windowrulev2",
            "0.47",
            "0.48",
            migrate_windowrule_v1_to_v2,
        ),
        _Migration(
            "Convert windowrulev2 → windowrule v3",
            "0.52",
            "0.53",
            migrate_windowrule_v2_to_v3,
        ),
        _Migration(
            "Remove dwindle:pseudotile (no-op since v0.55)",
            "0.54",
            "0.55",
            _make_delete_migration("dwindle:pseudotile"),
        ),
        _Migration(
            "Move misc:vfr → debug:vfr",
            "0.54",
            "0.55",
            _make_move_migration("misc:vfr", "debug:vfr"),
        ),
        _Migration(
            "Remove render:cm_fs_passthrough (automatic since v0.55)",
            "0.54",
            "0.55",
            _make_delete_migration("render:cm_fs_passthrough"),
        ),
        _Migration(
            "Remove decoration:shadow:ignore_window (always enabled since v0.55)",
            "0.54",
            "0.55",
            _make_delete_migration("decoration:shadow:ignore_window"),
        ),
        _Migration(
            "Move togglesplit/swapsplit/splitratio dispatchers to layoutmsg",
            "0.54",
            "0.55",
            _migrate_dispatchers_to_layoutmsg,
        ),
    ],
    key=lambda m: m.from_ver,
)


def migrate(
    doc: Document,
    *,
    from_version: str | None = None,
    to_version: str | None = None,
    recursive: bool | None = None,
) -> MigrationResult:
    """Apply known migration transforms to a document.

    Version-gated transforms are applied in version order.  Only
    migrations whose ``from_version`` falls within the
    ``[from_version, to_version)`` range are executed.

    After all version-gated migrations have rewritten any deprecated
    string syntax (v1 → v2 → v3 etc.), windowrule / layerrule lines —
    whether authored as block-form (``windowrule { name = …; …}``) or
    as single-line keywords (``windowrule = match:K V, EFFECT ARGS``)
    — are canonicalised into structured :class:`Rule` nodes so
    downstream consumers iterate the fields directly instead of
    re-parsing stringly-typed bodies. This normalisation runs
    unconditionally and isn't reported in the :class:`MigrationResult`.
    The post-pass order matters: version migrations rewrite Keyword
    values in place, so they need to see Keyword nodes; normalising
    first would steal their inputs.

    Parameters
    ----------
    doc:
        The document to migrate **in place**.
    from_version:
        The Hyprland version the config was written for.  Migrations older
        than this are skipped.
    to_version:
        The target Hyprland version.  Migrations newer than this are
        skipped.  Defaults to the latest known version.
    recursive:
        Whether to migrate sourced sub-documents.  Defaults to the
        document's ``sources_followed`` flag.

    Returns
    -------
    MigrationResult:
        Lists of applied and skipped migration descriptions.
    """
    result = MigrationResult()
    from_ver = parse_version(from_version) if from_version is not None else None
    to_ver = parse_version(to_version) if to_version is not None else None

    for m in _MIGRATIONS:
        if from_ver is not None and m.from_ver < from_ver:
            continue
        if to_ver is not None and m.from_ver >= to_ver:
            continue
        applied = False
        for target_doc in doc.target_documents(recursive):
            if m.transform(target_doc):
                applied = True
        if applied:
            result.applied.append(m.description)
        else:
            result.skipped.append(m.description)

    for target_doc in doc.target_documents(recursive):
        normalize_rules(target_doc)

    return result
