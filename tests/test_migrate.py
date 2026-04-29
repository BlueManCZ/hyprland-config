"""Tests for deprecation checking and migration helpers."""

from hyprland_config import KeyValueLine, check_deprecated, migrate, parse_file, parse_string


class TestCheckDeprecated:
    def test_detects_windowrule_v1(self):
        doc = parse_string("windowrule = float,Firefox\n")
        warnings = check_deprecated(doc)
        assert any("windowrule" in w.key and "deprecated" in w.message for w in warnings)

    def test_detects_blur_options(self):
        doc = parse_string("decoration {\n    blur_size = 3\n    blur_passes = 1\n}\n")
        warnings = check_deprecated(doc)
        blur_warnings = [w for w in warnings if "blur" in w.key]
        assert len(blur_warnings) == 2

    def test_detects_exec_once_underscore(self):
        doc = parse_string("exec_once = waybar\n")
        warnings = check_deprecated(doc)
        assert any("exec_once" in w.key for w in warnings)

    def test_detects_numlock_by_default(self):
        doc = parse_string("input {\n    numlock_by_default = true\n}\n")
        warnings = check_deprecated(doc)
        assert any("numlock" in w.key for w in warnings)

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
        assert "exec-once" in doc.serialize()

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
        assert "no_warps = true" in doc.serialize()

    def test_migrate_numlock(self):
        doc = parse_string("input {\n    numlock_by_default = true\n}\n")
        result = migrate(doc)
        assert result.changes_made
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].full_key == "input:kb_numlock"

    def test_migrate_windowrule_v1_chains_to_v3(self):
        # v1 (``windowrule = float,Firefox``) → v2 → v3 in one
        # ``migrate()`` call: the migrations chain by version order.
        doc = parse_string("windowrule = float,Firefox\n")
        result = migrate(doc)
        assert result.changes_made
        serialized = doc.serialize()
        # Final form is v3, not v2 — the chain runs both rewrites.
        assert "windowrulev2" not in serialized
        assert "windowrule = match:title Firefox, float on" in serialized

    def test_migrate_windowrule_v1_stops_at_v2_when_capped(self):
        # Capping to_version stops the chain at v2 — useful for tools
        # that want intermediate state.
        doc = parse_string("windowrule = float,Firefox\n")
        migrate(doc, to_version="0.52")
        serialized = doc.serialize()
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
        serialized = doc.serialize()
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
        out = doc.serialize()
        assert "windowrulev2" not in out
        assert "title:float on" not in out
        assert out.strip() == "windowrule = match:class ^(firefox)$, float on"

    def test_migrate_windowrule_v3_effect_first_not_back_to_v2(self):
        """v3 with effect first, matchers last — still must not migrate."""
        # Both orderings of v3 are valid; both must skip migration.
        doc = parse_string("windowrule = float on, match:class ^(firefox)$\n")
        migrate(doc)
        out = doc.serialize()
        assert "windowrulev2" not in out
        # The leading "float on" was the second-comma-part candidate
        # for being wrapped with ``title:`` under the old buggy
        # predicate. Confirm it stayed intact.
        assert "title:" not in out

    def test_migrate_windowrulev2_to_v3_basic(self):
        doc = parse_string("windowrulev2 = float, class:^(firefox)$\n")
        result = migrate(doc)
        assert result.changes_made
        out = doc.serialize()
        # Keyword renamed, matcher carries ``match:`` prefix and a
        # space, bool effect gained ``on`` argument.
        assert "windowrule = match:class ^(firefox)$, float on" in out

    def test_migrate_windowrulev2_to_v3_renamed_effect(self):
        # ``noblur`` → ``no_blur`` (v3 snake_case), gains ``on``.
        doc = parse_string("windowrulev2 = noblur, class:^(kitty)$\n")
        migrate(doc)
        out = doc.serialize()
        assert "windowrule = match:class ^(kitty)$, no_blur on" in out

    def test_migrate_windowrulev2_to_v3_renamed_matcher(self):
        # ``initialClass`` → ``initial_class``.
        doc = parse_string("windowrulev2 = float, initialClass:^(firefox)$\n")
        migrate(doc)
        out = doc.serialize()
        assert "match:initial_class ^(firefox)$" in out

    def test_migrate_windowrulev2_to_v3_negation(self):
        # v2's ``~class:foo`` becomes ``match:class negative:foo``.
        doc = parse_string("windowrulev2 = float, ~class:^(firefox)$\n")
        migrate(doc)
        out = doc.serialize()
        assert "match:class negative:^(firefox)$" in out

    def test_migrate_windowrulev2_to_v3_multiarg_effect(self):
        # ``opacity 0.5 0.8`` keeps its args after the rename.
        doc = parse_string("windowrulev2 = opacity 0.5 0.8, class:^(kitty)$\n")
        migrate(doc)
        out = doc.serialize()
        assert "windowrule = match:class ^(kitty)$, opacity 0.5 0.8" in out

    def test_migrate_windowrulev2_to_v3_multi_matcher(self):
        # v2 supports space-separated matchers; v3 uses comma-separated
        # ``match:`` tokens. Both matchers must carry over.
        doc = parse_string("windowrulev2 = float, class:^(kitty)$ title:^(scratch)$\n")
        migrate(doc)
        out = doc.serialize()
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
        out = doc.serialize()
        assert "title:opacity" not in out
        assert "windowrule = match:class ^(ghostty)$, opacity 0.8" in out

    def test_migrate_windowrulev2_to_v3_corruption_recovery_with_bool_effect(self):
        # Same corruption pattern with a bool effect that needs ``on``
        # appended. The recovery just strips ``title:``; the effect's
        # original ``on`` is already present in the captured args.
        doc = parse_string(r"windowrulev2 = match:class ^(firefox)$, title:float on" + "\n")
        migrate(doc)
        out = doc.serialize()
        assert "title:float" not in out
        assert "windowrule = match:class ^(firefox)$, float on" in out

    def test_migrate_windowrulev2_real_v2_with_title_matcher_not_corrupted(self):
        # A real v2 line whose only matcher happens to be ``title:foo``
        # (no ``match:`` token anywhere) must NOT be treated as
        # corruption — the recovery branch fires only when ``match:``
        # is present.
        doc = parse_string("windowrulev2 = float, title:^(scratch)$\n")
        migrate(doc)
        out = doc.serialize()
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
        assert doc.serialize() == "decoration:blur:size = 8\n"

    def test_sectioned_blur_option_stays_sectioned(self):
        doc = parse_string("decoration {\n    blur_size = 8\n}\n")
        migrate(doc)
        # The leaf-only rewrite is correct inside a section block.
        assert "    size = 8\n" in doc.serialize()
        # And the full_key still reflects the new nested path.
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].full_key == "decoration:blur:size"
        assert kv[0].key == "size"

    def test_flat_no_cursor_warps_stays_flat(self):
        doc = parse_string("cursor:no_cursor_warps = true\n")
        migrate(doc)
        assert doc.serialize() == "cursor:no_warps = true\n"
        kv = [ln for ln in doc.lines if isinstance(ln, KeyValueLine)]
        assert kv[0].key == "cursor:no_warps"
        assert kv[0].full_key == "cursor:no_warps"

    def test_flat_numlock_stays_flat(self):
        doc = parse_string("input:numlock_by_default = true\n")
        migrate(doc)
        assert doc.serialize() == "input:kb_numlock = true\n"

    def test_flat_sensitivity_stays_flat(self):
        doc = parse_string("general:sensitivity = 1.0\n")
        migrate(doc)
        assert doc.serialize() == "input:sensitivity = 1.0\n"
