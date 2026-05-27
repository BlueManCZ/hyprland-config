"""Tests for deprecation checking and migration helpers."""

from hyprland_config import (
    check_deprecated,
    migrate,
    parse_string,
    serialize_hyprlang,
)
from hyprland_config._core._model import KeyValueLine
from hyprland_config._hyprlang import parse_file


class TestCheckDeprecated:
    def test_detects_windowrule_v1(self):
        doc = parse_string("windowrule = float,Firefox\n")
        warnings = check_deprecated(doc)
        assert any("windowrule" in w.key and "deprecated" in w.message for w in warnings)

    def test_does_not_flag_windowrule_v3(self):
        """v3 lines reuse the ``windowrule`` keyword but carry ``match:`` tokens."""
        doc = parse_string("windowrule = stay_focused on, match:title ^Albert$\n")
        warnings = check_deprecated(doc)
        assert not any("windowrule" in w.key for w in warnings)

    def test_does_not_flag_windowrule_v3_multi_matchers(self):
        """v3 lines can chain multiple ``match:`` tokens."""
        doc = parse_string("windowrule = float on, match:class firefox, match:title settings\n")
        warnings = check_deprecated(doc)
        assert not any("windowrule" in w.key for w in warnings)

    def test_detects_blur_options(self):
        doc = parse_string("decoration {\n    blur_size = 3\n    blur_passes = 1\n}\n")
        warnings = check_deprecated(doc)
        blur_warnings = [w for w in warnings if "blur" in w.key]
        assert len(blur_warnings) == 2

    def test_detects_exec_once_underscore(self):
        doc = parse_string("exec_once = waybar\n")
        warnings = check_deprecated(doc)
        assert any("exec_once" in w.key for w in warnings)

    def test_detects_general_max_fps(self):
        doc = parse_string("general {\n    max_fps = 60\n}\n")
        warnings = check_deprecated(doc)
        assert any("max_fps" in w.key for w in warnings)

    def test_detects_sensitivity_in_general(self):
        doc = parse_string("general {\n    sensitivity = 1.0\n}\n")
        warnings = check_deprecated(doc)
        assert any("sensitivity" in w.key for w in warnings)

    def test_min_version_filters_old_rules(self):
        doc = parse_string("exec_once = waybar\n")
        # exec_once deprecated in 0.33; min_version=0.40 should skip it
        warnings = check_deprecated(doc, min_version="0.40")
        assert not any("exec_once" in w.key for w in warnings)

    def test_hyprland_version_filters_newer_rules(self):
        """Rules deprecated above the running Hyprland version are skipped."""
        # windowrulev2 deprecated in 0.53; user on 0.49 sees no such warning.
        doc = parse_string("windowrulev2 = float, class:^(firefox)$\n")
        warnings = check_deprecated(doc, hyprland_version="0.49")
        assert not any(w.key == "windowrulev2" for w in warnings)
        # dwindle:pseudotile deprecated in 0.55; user on 0.49 sees no such warning.
        doc = parse_string("dwindle {\n    pseudotile = 1\n}\n")
        warnings = check_deprecated(doc, hyprland_version="0.49")
        assert not any(w.key == "dwindle:pseudotile" for w in warnings)

    def test_hyprland_version_boundary_is_inclusive(self):
        """A rule deprecated *at* the running version is still reported."""
        # pseudotile deprecated in 0.55; user on 0.55 should see it.
        doc = parse_string("dwindle {\n    pseudotile = 1\n}\n")
        warnings = check_deprecated(doc, hyprland_version="0.55")
        assert any(w.key == "dwindle:pseudotile" for w in warnings)

    def test_hyprland_version_still_flags_older_deprecations(self):
        """Pre-existing deprecations remain visible at higher Hyprland versions."""
        # windowrule v1 deprecated in 0.48; visible to a 0.49 user.
        doc = parse_string("windowrule = float,Firefox\n")
        warnings = check_deprecated(doc, hyprland_version="0.49")
        assert any("windowrule" in w.key and "deprecated" in w.message for w in warnings)

    def test_hyprland_version_with_patch_suffix(self):
        """``0.49.0`` parses and compares equivalently to ``0.49``."""
        doc = parse_string("windowrulev2 = float, class:^(firefox)$\n")
        warnings = check_deprecated(doc, hyprland_version="0.49.0")
        assert not any(w.key == "windowrulev2" for w in warnings)

    def test_no_false_positives_on_clean_config(self):
        doc = parse_string(
            "$mainMod = SUPER\n"
            "general {\n"
            "    gaps_in = 5\n"
            "    gaps_out = 10\n"
            "}\n"
            "bind = $mainMod, Q, killactive\n"
        )
        warnings = check_deprecated(doc)
        assert len(warnings) == 0

    def test_warning_str_format(self):
        doc = parse_string("exec_once = waybar\n")
        warnings = check_deprecated(doc)
        w = next(w for w in warnings if "exec_once" in w.key)
        s = str(w)
        assert "deprecated" in s
        assert "exec-once" in s

    def test_detects_no_vfr(self):
        doc = parse_string("misc {\n    no_vfr = true\n}\n")
        warnings = check_deprecated(doc)
        assert any("no_vfr" in w.key for w in warnings)

    def test_detects_pseudotile(self):
        doc = parse_string("dwindle {\n    pseudotile = 1\n}\n")
        warnings = check_deprecated(doc)
        assert any(w.key == "dwindle:pseudotile" for w in warnings)

    def test_detects_vfr_in_misc(self):
        doc = parse_string("misc {\n    vfr = false\n}\n")
        warnings = check_deprecated(doc)
        moved = [w for w in warnings if w.key == "misc:vfr"]
        assert moved and "debug:vfr" in moved[0].suggestion

    def test_detects_cm_fs_passthrough(self):
        doc = parse_string("render {\n    cm_fs_passthrough = 2\n}\n")
        warnings = check_deprecated(doc)
        assert any(w.key == "render:cm_fs_passthrough" for w in warnings)

    def test_detects_shadow_ignore_window(self):
        doc = parse_string("decoration {\n    shadow {\n        ignore_window = true\n    }\n}\n")
        warnings = check_deprecated(doc)
        assert any(w.key == "decoration:shadow:ignore_window" for w in warnings)

    def test_recursive_checks_sourced_docs(self, tmp_path):
        """check_deprecated follows sources when recursive."""
        sub = tmp_path / "sub.conf"
        sub.write_text("exec_once = waybar\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = parse_file(main, follow_sources=True)
        warnings = check_deprecated(doc)
        assert any("exec_once" in w.key for w in warnings)


class TestMigrate:
    def test_migrate_exec_once(self):
        doc = parse_string("exec_once = waybar\n")
        result = migrate(doc)
        assert result.changes_made
        assert any("exec_once" in d for d in result.applied)
        assert isinstance(doc.lines[0], KeyValueLine) and doc.lines[0].key == "exec-once"
        assert "exec-once" in serialize_hyprlang(doc)

    def test_migrate_blur_options(self):
        doc = parse_string("decoration {\n    blur_size = 3\n    blur_passes = 1\n}\n")
        result = migrate(doc)
        assert result.changes_made
        # Keys should be updated
        kv_lines = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        keys = [ln.full_key for ln in kv_lines]
        assert "decoration:blur:size" in keys
        assert "decoration:blur:passes" in keys

    def test_migrate_no_cursor_warps(self):
        doc = parse_string("cursor {\n    no_cursor_warps = true\n}\n")
        result = migrate(doc)
        assert result.changes_made
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].full_key == "cursor:no_warps"
        assert kv[0].key == "no_warps"
        assert "no_warps = true" in serialize_hyprlang(doc)

    def test_migrate_windowrule_v1_chains_to_v3(self):
        # v1 (``windowrule = float,Firefox``) → v2 → v3 in one
        # ``migrate()`` call: the migrations chain by version order.
        doc = parse_string("windowrule = float,Firefox\n")
        result = migrate(doc)
        assert result.changes_made
        serialized = serialize_hyprlang(doc)
        # Final form is v3, not v2 — the chain runs both rewrites.
        assert "windowrulev2" not in serialized
        assert "windowrule = match:title Firefox, float on" in serialized

    def test_migrate_windowrule_v1_stops_at_v2_when_capped(self):
        # Capping to_version stops the chain at v2 — useful for tools
        # that want intermediate state.
        doc = parse_string("windowrule = float,Firefox\n")
        migrate(doc, to_version="0.52")
        serialized = serialize_hyprlang(doc)
        assert "windowrulev2" in serialized
        assert "title:Firefox" in serialized

    def test_migrate_windowrule_v1_keyword_with_v2_syntax_stays_alone(self):
        # ``windowrule = float,title:Firefox`` is malformed — v1
        # keyword with v2-style ``title:`` matcher. v1→v2 skips it
        # because the second part already starts with a v2 prefix
        # (would otherwise double-wrap as ``title:title:``); v2→v3
        # skips it because the keyword isn't ``windowrulev2``. The
        # line is left as-is rather than guessing what the author
        # meant.
        doc = parse_string("windowrule = float,title:Firefox\n")
        migrate(doc)
        serialized = serialize_hyprlang(doc)
        assert "title:title:" not in serialized
        # Stays unchanged — neither migration claims it.
        assert "windowrule = float,title:Firefox" in serialized

    def test_migrate_windowrule_v3_not_back_to_v2(self):
        """v3 lines (Hyprland 0.53+) must NOT trigger the v1→v2 migration.

        Regression: the v1→v2 predicate split the line value on the
        first comma and checked if the *second* part started with a
        v2 prefix (``title:``, ``class:``, …). v3 lines look like
        ``windowrule = match:class foo, float on``. Both halves of
        the comma split fail the v2-prefix check, so the migration
        wrongly fired and corrupted the line into
        ``windowrulev2 = match:class foo, title:float on`` —
        which Hyprland 0.53+ then rejects, since v2 is itself
        deprecated and ``title:float on`` is nonsense.

        The fix: skip migration on any ``windowrule = …`` line that
        contains at least one ``match:`` token (the v3 marker).
        """
        # v3 with matchers first, effect last
        doc = parse_string("windowrule = match:class ^(firefox)$, float on\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "windowrulev2" not in out
        assert "title:float on" not in out
        assert out.strip() == "windowrule = match:class ^(firefox)$, float on"

    def test_migrate_windowrule_v3_effect_first_not_back_to_v2(self):
        """v3 with effect first, matchers last — still must not migrate."""
        # Both orderings of v3 are valid; both must skip migration.
        doc = parse_string("windowrule = float on, match:class ^(firefox)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "windowrulev2" not in out
        # The leading "float on" was the second-comma-part candidate
        # for being wrapped with ``title:`` under the old buggy
        # predicate. Confirm it stayed intact.
        assert "title:" not in out

    def test_migrate_windowrulev2_to_v3_basic(self):
        doc = parse_string("windowrulev2 = float, class:^(firefox)$\n")
        result = migrate(doc)
        assert result.changes_made
        out = serialize_hyprlang(doc)
        # Keyword renamed, matcher carries ``match:`` prefix and a
        # space, bool effect gained ``on`` argument.
        assert "windowrule = match:class ^(firefox)$, float on" in out

    def test_migrate_windowrulev2_to_v3_renamed_effect(self):
        # ``noblur`` → ``no_blur`` (v3 snake_case), gains ``on``.
        doc = parse_string("windowrulev2 = noblur, class:^(kitty)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "windowrule = match:class ^(kitty)$, no_blur on" in out

    def test_migrate_windowrulev2_to_v3_renamed_matcher(self):
        # ``initialClass`` → ``initial_class``.
        doc = parse_string("windowrulev2 = float, initialClass:^(firefox)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "match:initial_class ^(firefox)$" in out

    def test_migrate_windowrulev2_to_v3_negation(self):
        # v2's ``~class:foo`` becomes ``match:class negative:foo``.
        doc = parse_string("windowrulev2 = float, ~class:^(firefox)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "match:class negative:^(firefox)$" in out

    def test_migrate_windowrulev2_to_v3_multiarg_effect(self):
        # ``opacity 0.5 0.8`` keeps its args after the rename.
        doc = parse_string("windowrulev2 = opacity 0.5 0.8, class:^(kitty)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "windowrule = match:class ^(kitty)$, opacity 0.5 0.8" in out

    def test_migrate_windowrulev2_to_v3_multi_matcher(self):
        # v2 supports space-separated matchers; v3 uses comma-separated
        # ``match:`` tokens. Both matchers must carry over.
        doc = parse_string("windowrulev2 = float, class:^(kitty)$ title:^(scratch)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "match:class ^(kitty)$" in out
        assert "match:title ^(scratch)$" in out
        assert "float on" in out

    def test_migrate_windowrulev2_to_v3_corruption_recovery(self):
        # Recovery for the ``hyprland-config<0.4.4`` corruption: v3
        # syntax incorrectly wrapped as v2 with a stray ``title:``
        # prepended to the effect token. The migration recognises the
        # v3-only ``match:`` marker and strips the bogus ``title:``.
        doc = parse_string(r"windowrulev2 = match:class ^(ghostty)$, title:opacity 0.8" + "\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "title:opacity" not in out
        assert "windowrule = match:class ^(ghostty)$, opacity 0.8" in out

    def test_migrate_windowrulev2_to_v3_corruption_recovery_with_bool_effect(self):
        # Same corruption pattern with a bool effect that needs ``on``
        # appended. The recovery just strips ``title:``; the effect's
        # original ``on`` is already present in the captured args.
        doc = parse_string(r"windowrulev2 = match:class ^(firefox)$, title:float on" + "\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "title:float" not in out
        assert "windowrule = match:class ^(firefox)$, float on" in out

    def test_migrate_windowrulev2_to_v3_regex_with_spaces(self):
        doc = parse_string("windowrulev2 = float, title:(^Settings — Albert$)\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "match:title (^Settings — Albert$)" in out
        assert "float on" in out

    def test_migrate_windowrulev2_to_v3_regex_single_space(self):
        doc = parse_string("windowrulev2 = center,class:^(jetbrains-.*)$,title:^( )$,floating:1\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "match:title ^( )$" in out
        assert "match:class ^(jetbrains-.*)$" in out
        assert "match:float 1" in out
        assert "center on" in out

    def test_migrate_windowrulev2_to_v3_noborder_becomes_border_size_0(self):
        doc = parse_string("windowrulev2 = noborder, class:^(jetbrains-.*)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "border_size 0" in out
        assert "no_border" not in out

    def test_migrate_windowrulev2_to_v3_norounding_becomes_rounding_0(self):
        doc = parse_string("windowrulev2 = norounding, class:^(kitty)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "rounding 0" in out
        assert "no_rounding" not in out

    def test_migrate_windowrulev2_real_v2_with_title_matcher_not_corrupted(self):
        # A real v2 line whose only matcher happens to be ``title:foo``
        # (no ``match:`` token anywhere) must NOT be treated as
        # corruption — the recovery branch fires only when ``match:``
        # is present.
        doc = parse_string("windowrulev2 = float, title:^(scratch)$\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        # Translated as v2 → v3: the ``title:`` is a v2 matcher, not
        # a corruption marker.
        assert "windowrule = match:title ^(scratch)$, float on" in out

    def test_migrate_version_range(self):
        doc = parse_string("exec_once = waybar\n")
        # from_version=0.40 should skip exec_once (deprecated in 0.33)
        result = migrate(doc, from_version="0.40")
        assert not any("exec_once" in d for d in result.applied)

    def test_migrate_no_changes_on_clean_config(self):
        doc = parse_string("bind = SUPER, Q, killactive\nexec-once = waybar\n")
        result = migrate(doc)
        assert not result.changes_made

    def test_migrate_marks_dirty(self):
        doc = parse_string("exec_once = waybar\n")
        assert not doc.dirty
        migrate(doc)
        assert doc.dirty

    def test_migration_result_str(self):
        result = migrate(parse_string("exec_once = waybar\n"))
        assert isinstance(result.applied, list)
        assert isinstance(result.skipped, list)


class TestMigratePreservesLineShape:
    """Flat colon-prefixed lines must stay flat; sectioned lines must stay sectioned.

    Regression: ``decoration:blur_size = 8`` at top level used to serialize as
    ``size = 8`` after migration because the rewrite only used the leaf key.
    """

    def test_flat_blur_option_stays_flat(self):
        doc = parse_string("decoration:blur_size = 8\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == "decoration:blur:size = 8\n"

    def test_sectioned_blur_option_stays_sectioned(self):
        doc = parse_string("decoration {\n    blur_size = 8\n}\n")
        migrate(doc)
        # The leaf-only rewrite is correct inside a section block.
        assert "    size = 8\n" in serialize_hyprlang(doc)
        # And the full_key still reflects the new nested path.
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].full_key == "decoration:blur:size"
        assert kv[0].key == "size"

    def test_flat_no_cursor_warps_stays_flat(self):
        doc = parse_string("cursor:no_cursor_warps = true\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == "cursor:no_warps = true\n"
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].key == "cursor:no_warps"
        assert kv[0].full_key == "cursor:no_warps"

    def test_flat_sensitivity_stays_flat(self):
        doc = parse_string("general:sensitivity = 1.0\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == "input:sensitivity = 1.0\n"


class TestMigrateV055:
    """Migrations for Hyprland v0.55 breaking changes."""

    def test_delete_pseudotile_sectioned(self):
        doc = parse_string(
            "dwindle {\n    pseudotile = 1 # master switch\n    preserve_split = 1\n}\n"
        )
        result = migrate(doc)
        assert result.changes_made
        out = serialize_hyprlang(doc)
        assert "pseudotile" not in out
        # Other options in the section survive.
        assert "preserve_split = 1" in out

    def test_delete_pseudotile_flat(self):
        doc = parse_string("dwindle:pseudotile = 1\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == ""

    def test_delete_cm_fs_passthrough(self):
        doc = parse_string(
            "render {\n\tcm_auto_hdr = true\n\tcm_fs_passthrough = 2\n\tdirect_scanout = 1\n}\n"
        )
        result = migrate(doc)
        assert result.changes_made
        out = serialize_hyprlang(doc)
        assert "cm_fs_passthrough" not in out
        assert "cm_auto_hdr = true" in out
        assert "direct_scanout = 1" in out

    def test_delete_shadow_ignore_window_nested(self):
        # Nested decoration:shadow section — leaf rewrite stays inside.
        doc = parse_string(
            "decoration {\n"
            "    shadow {\n"
            "        enabled = true\n"
            "        ignore_window = true\n"
            "    }\n"
            "}\n"
        )
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "ignore_window" not in out
        assert "enabled = true" in out

    def test_delete_shadow_ignore_window_flat(self):
        doc = parse_string("decoration:shadow:ignore_window = true\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == ""

    def test_move_vfr_flat(self):
        doc = parse_string("misc:vfr = false\n")
        migrate(doc)
        assert serialize_hyprlang(doc) == "debug:vfr = false\n"

    def test_move_vfr_sectioned_creates_debug_section(self):
        # No pre-existing debug block — the migration creates one.
        doc = parse_string("misc {\n    vrr = 1\n    vfr = false\n}\n")
        result = migrate(doc)
        assert result.changes_made
        out = serialize_hyprlang(doc)
        # vfr removed from misc
        assert "    vfr = false\n" not in out.split("misc {")[1].split("}")[0]
        # New debug section exists with vfr inside.
        assert "debug {" in out
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        vfr_lines = [ln for ln in kv if ln.full_key == "debug:vfr"]
        assert len(vfr_lines) == 1
        assert vfr_lines[0].value == "false"

    def test_move_vfr_sectioned_uses_existing_debug_section(self):
        # Pre-existing debug block — vfr lands inside it, not in a new block.
        doc = parse_string("misc {\n    vfr = false\n}\n\ndebug {\n    overlay = true\n}\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        # Only one debug { opening — no duplicate section.
        assert out.count("debug {") == 1
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert any(ln.full_key == "debug:vfr" and ln.value == "false" for ln in kv)
        assert any(ln.full_key == "debug:overlay" for ln in kv)

    def test_move_vfr_preserves_inline_comment(self):
        # The round-trip-preserves-comments promise extends to migrations:
        # an inline comment on a sectioned line must survive the move.
        doc = parse_string("misc {\n    vfr = false # battery friendly\n}\n")
        migrate(doc)
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        vfr = next(ln for ln in kv if ln.full_key == "debug:vfr")
        assert vfr.inline_comment == "# battery friendly"
        assert "# battery friendly" in serialize_hyprlang(doc)

    def test_migrate_real_v055_breaking_config(self):
        # The exact shape that caused the v0.55 error report.
        doc = parse_string(
            "dwindle {\n"
            "    pseudotile = 1\n"
            "    preserve_split = 1\n"
            "}\n"
            "\n"
            "misc {\n"
            "    vrr = 1\n"
            "    vfr = false\n"
            "}\n"
            "\n"
            "debug {\n"
            "}\n"
            "\n"
            "render {\n"
            "    cm_auto_hdr = true\n"
            "    cm_fs_passthrough = 2\n"
            "    direct_scanout = 1\n"
            "}\n"
        )
        migrate(doc)
        # Re-check should now produce zero v0.55 warnings.
        warnings = check_deprecated(doc, min_version="0.55")
        assert warnings == []

    def test_dispatcher_togglesplit_to_layoutmsg(self):
        doc = parse_string("bind = $mainMod, J, togglesplit\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "layoutmsg, togglesplit" in out
        assert "togglesplit" in out
        assert out.count("togglesplit") == 1

    def test_dispatcher_swapsplit_to_layoutmsg(self):
        doc = parse_string("bind = $mainMod, K, swapsplit\n")
        migrate(doc)
        assert "layoutmsg, swapsplit" in serialize_hyprlang(doc)

    def test_dispatcher_splitratio_to_layoutmsg_with_args(self):
        doc = parse_string("binde = $mainMod, minus, splitratio, -0.1\n")
        migrate(doc)
        out = serialize_hyprlang(doc)
        assert "layoutmsg, splitratio -0.1" in out

    def test_dispatcher_migration_skips_unrelated_binds(self):
        doc = parse_string("bind = SUPER, Q, killactive\n")
        migrate(doc)
        assert "killactive" in serialize_hyprlang(doc)
        assert "layoutmsg" not in serialize_hyprlang(doc)

    def test_dispatcher_deprecation_detected(self):
        doc = parse_string("bind = $mainMod, J, togglesplit\n")
        warnings = check_deprecated(doc)
        assert any("togglesplit" in w.message for w in warnings)

    def test_dispatcher_deprecation_not_flagged_after_migrate(self):
        doc = parse_string("bind = $mainMod, J, togglesplit\n")
        migrate(doc)
        warnings = check_deprecated(doc)
        assert not any("togglesplit" in w.message for w in warnings)

    def test_from_version_skips_055_for_older_target(self):
        # User on Hyprland 0.54 should not get their pseudotile removed.
        doc = parse_string("dwindle {\n    pseudotile = 1\n}\n")
        migrate(doc, to_version="0.54")
        assert "pseudotile = 1" in serialize_hyprlang(doc)


def _rules_of_kind(doc, kind: str):
    from hyprland_config import Rule

    return [ln for ln in doc.lines if isinstance(ln, Rule) and ln.kind == kind]


class TestNormalizeRules:
    """Both authored shapes (single-line ``windowrule = …`` and block
    ``windowrule { … }``) canonicalise into structured :class:`Rule`
    nodes after ``migrate()`` runs.
    """

    def test_block_form_named_windowrule(self):
        # The exact shape from hyprmod issue #37.
        doc = parse_string(
            "windowrule {\n"
            "    name = apply-something\n"
            "    match:class = my-window\n"
            "    border_size = 10\n"
            "}\n"
        )
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "apply-something"
        assert rules[0].enabled is True
        assert rules[0].matchers == [("class", "my-window")]
        assert rules[0].effects == [("border_size", "10")]

    def test_section_key_form_carries_name(self):
        # ``windowrule[my-name] { … }`` puts the name in the section key.
        doc = parse_string("windowrule[my-name] {\n    match:class = kitty\n    float = on\n}\n")
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "my-name"
        assert rules[0].effects == [("float", "on")]

    def test_explicit_name_overrides_section_key(self):
        doc = parse_string(
            "windowrule[from-key] {\n"
            "    name = from-assignment\n"
            "    match:class = X\n"
            "    float = on\n"
            "}\n"
        )
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert rules[0].name == "from-assignment"

    def test_block_with_multiple_effects(self):
        doc = parse_string(
            "windowrule {\n"
            "    name = bundle\n"
            "    match:class = kitty\n"
            "    border_size = 5\n"
            "    no_blur = on\n"
            "    opacity = 0.9\n"
            "}\n"
        )
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "bundle"
        assert [e[0] for e in rules[0].effects] == ["border_size", "no_blur", "opacity"]

    def test_disabled_block_rule(self):
        doc = parse_string(
            "windowrule {\n"
            "    name = off-by-default\n"
            "    enable = 0\n"
            "    match:class = X\n"
            "    float = on\n"
            "}\n"
        )
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert rules[0].name == "off-by-default"
        assert rules[0].enabled is False

    def test_anonymous_block(self):
        doc = parse_string("windowrule {\n    match:class = X\n    float = on\n}\n")
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == ""
        assert rules[0].effects == [("float", "on")]

    def test_layerrule_block(self):
        doc = parse_string(
            "layerrule {\n"
            "    name = no-anim-selection\n"
            "    match:namespace = selection\n"
            "    no_anim = on\n"
            "}\n"
        )
        migrate(doc)
        rules = _rules_of_kind(doc, "layerrule")
        assert len(rules) == 1
        assert rules[0].name == "no-anim-selection"
        assert rules[0].matchers == [("namespace", "selection")]
        assert rules[0].effects == [("no_anim", "on")]

    def test_block_with_no_effects_preserved(self):
        # Hyprland rejects effectless rules; preserving the block
        # verbatim is safer than synthesising a half-rule and lets
        # tooling display the user's content as-is.
        from hyprland_config import Rule

        doc = parse_string("windowrule {\n    name = empty\n    match:class = X\n}\n")
        migrate(doc)
        assert not any(isinstance(ln, Rule) for ln in doc.lines)
        assert "windowrule {" in serialize_hyprlang(doc)

    def test_unclosed_block_preserved(self):
        from hyprland_config import Rule

        doc = parse_string(
            "windowrule {\n    name = X\n    match:class = Y\n    float = on\n",
            lenient=True,
        )
        migrate(doc)
        # No Rule node emitted; original SectionOpen preserved.
        assert not any(isinstance(ln, Rule) for ln in doc.lines)

    def test_single_line_keyword_becomes_rule(self):
        # The compact ``windowrule = …`` form normalises too — the
        # only difference vs. block form is that it can't carry a
        # name or enable flag.
        doc = parse_string("windowrule = match:class kitty, float on\n")
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == ""
        assert rules[0].matchers == [("class", "kitty")]
        assert rules[0].effects == [("float", "on")]

    def test_single_line_multi_effect_stays_bundled(self):
        # An anonymous multi-effect single-line stays as ONE Rule with
        # multiple effects — splitting was a hyprmod-specific workaround
        # that no longer applies once Rule supports multiple effects.
        doc = parse_string("windowrule = match:class kitty, opacity 0.8, no_blur on\n")
        migrate(doc)
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert [e[0] for e in rules[0].effects] == ["opacity", "no_blur"]

    def test_normalize_runs_when_from_version_is_above_055(self):
        # Rule normalisation isn't a deprecation — it runs unconditionally.
        doc = parse_string(
            "windowrule {\n    name = future-proof\n    match:class = X\n    float = on\n}\n"
        )
        migrate(doc, from_version="0.60")
        rules = _rules_of_kind(doc, "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "future-proof"

    def test_normalize_recurses_into_sourced_documents(self, tmp_path):
        sourced = tmp_path / "rules.conf"
        sourced.write_text(
            "windowrule {\n    name = from-source\n    match:class = X\n    float = on\n}\n"
        )
        root = tmp_path / "hyprland.conf"
        root.write_text(f"source = {sourced}\n")
        doc = parse_file(root, follow_sources=True)
        migrate(doc, recursive=True)
        from hyprland_config import Source

        for ln in doc.lines:
            if isinstance(ln, Source):
                sub = ln.documents[0]
                rules = _rules_of_kind(sub, "windowrule")
                assert len(rules) == 1
                assert rules[0].name == "from-source"
                break
