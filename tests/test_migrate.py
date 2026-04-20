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

    def test_migrate_windowrule_v1_to_v2(self):
        doc = parse_string("windowrule = float,Firefox\n")
        result = migrate(doc)
        assert result.changes_made
        serialized = doc.serialize()
        assert "windowrulev2" in serialized
        assert "title:Firefox" in serialized

    def test_migrate_windowrule_v2_not_converted(self):
        """Already using v2 match syntax — should not be converted."""
        doc = parse_string("windowrule = float,title:Firefox\n")
        migrate(doc)
        # The windowrule v1→v2 migration should skip this
        serialized = doc.serialize()
        assert "title:title:" not in serialized

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
