"""Tests for the Document model: query API, mutation API, and dirty tracking."""

from hyprland_config import (
    Assignment,
    load,
    parse_string,
)

# ---------------------------------------------------------------------------
# Variable handling
# ---------------------------------------------------------------------------


class TestVariables:
    def test_variable_accumulation(self):
        doc = parse_string("$a = hello\n$b = world\n")
        assert doc.variables == {"a": "hello", "b": "world"}

    def test_expand(self):
        doc = parse_string("$mainMod = SUPER\n")
        assert doc.expand("$mainMod + Q") == "SUPER + Q"

    def test_expand_multiple(self):
        doc = parse_string("$a = hello\n$b = world\n")
        assert doc.expand("$a $b") == "hello world"

    def test_expand_no_match(self):
        doc = parse_string("$a = hello\n")
        assert doc.expand("$unknown") == "$unknown"

    def test_expand_prefix_collision(self):
        """$a must not clobber $ab when both are defined."""
        doc = parse_string("$a = short\n$ab = long\n")
        assert doc.expand("$ab") == "long"
        assert doc.expand("$a and $ab") == "short and long"


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------


class TestDocumentAPI:
    def test_find(self):
        doc = parse_string("general {\n    gaps_in = 5\n    gaps_out = 10\n}\n")
        found = doc.find("general:gaps_in")
        assert found is not None
        assert isinstance(found, Assignment)
        assert found.value == "5"

    def test_find_not_found(self):
        doc = parse_string("key = value\n")
        assert doc.find("nonexistent") is None

    def test_find_all(self):
        text = "bind = SUPER, Q, killactive,\nbind = SUPER, Return, exec, kitty\n"
        doc = parse_string(text)
        found = doc.find_all("bind")
        assert len(found) == 2

    def test_find_last_wins(self):
        doc = parse_string("key = first\nkey = second\n")
        found = doc.find("key")
        assert found is not None and found.value == "second"

    def test_get_existing(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        assert doc.get("general:gaps_in") == "5"

    def test_get_missing_returns_none(self):
        doc = parse_string("key = value\n")
        assert doc.get("nonexistent") is None

    def test_get_missing_returns_default(self):
        doc = parse_string("key = value\n")
        assert doc.get("nonexistent", "fallback") == "fallback"

    def test_get_keyword(self):
        doc = parse_string("bind = SUPER, Q, killactive,\n")
        assert doc.get("bind") == "SUPER, Q, killactive,"

    def test_get_all(self):
        doc = parse_string("bind = SUPER, Q, killactive,\nbind = SUPER, Return, exec, kitty\n")
        assert doc.get_all("bind") == [
            "SUPER, Q, killactive,",
            "SUPER, Return, exec, kitty",
        ]

    def test_get_all_empty(self):
        doc = parse_string("key = value\n")
        assert doc.get_all("bind") == []

    # -- Keywords match regardless of section context --

    def test_find_keyword_in_section_by_bare_key(self):
        """Keywords inside sections match by bare key (Hyprland ignores context)."""
        doc = parse_string("animations {\n    animation = windows, 1, 3, default\n}\n")
        found = doc.find("animation")
        assert found is not None
        assert found.value == "windows, 1, 3, default"

    def test_find_all_keyword_across_sections(self):
        """find_all collects keywords both inside and outside sections."""
        doc = parse_string(
            "animation = fade, 1, 5, default\n"
            "animations {\n    animation = windows, 1, 3, default\n}\n"
        )
        found = doc.find_all("animation")
        assert len(found) == 2
        names = [kw.value.split(",")[0].strip() for kw in found]
        assert "fade" in names
        assert "windows" in names

    def test_find_keyword_in_section_by_full_key(self):
        """Section-qualified lookup still works for backwards compat."""
        doc = parse_string("animations {\n    animation = windows, 1, 3, default\n}\n")
        found = doc.find("animations:animation")
        assert found is not None

    def test_assignment_not_matched_by_bare_key(self):
        """Assignments still require full section-qualified key."""
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        assert doc.find("gaps_in") is None
        assert doc.find("general:gaps_in") is not None


# ---------------------------------------------------------------------------
# Mutation API
# ---------------------------------------------------------------------------


class TestSet:
    def test_update_existing(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        doc.set("general:gaps_in", "10")
        node = doc.find("general:gaps_in")
        assert node is not None and node.value == "10"
        assert "gaps_in = 10\n" in doc.serialize()

    def test_update_preserves_indentation(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        doc.set("general:gaps_in", "10")
        assert doc.serialize() == "general {\n    gaps_in = 10\n}\n"

    def test_update_preserves_inline_comment(self):
        doc = parse_string("key = old # keep this\n")
        doc.set("key", "new")
        assert doc.serialize() == "key = new # keep this\n"

    def test_update_last_occurrence(self):
        doc = parse_string("key = first\nkey = second\n")
        doc.set("key", "third")
        lines = doc.serialize()
        assert "key = first\n" in lines
        assert "key = third\n" in lines
        assert "second" not in lines

    def test_insert_into_existing_section(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        doc.set("general:gaps_out", "10")
        result = doc.serialize()
        assert "gaps_out = 10" in result
        # Should be inside the section (before closing brace)
        assert result.index("gaps_out") < result.index("}")

    def test_insert_nested_section(self):
        text = "decoration {\n    rounding = 10\n    shadow {\n        range = 10\n    }\n}\n"
        doc = parse_string(text)
        doc.set("decoration:shadow:color", "rgba(000000ee)")
        result = doc.serialize()
        assert "color = rgba(000000ee)" in result
        assert result.index("color") < result.rindex("}")

    def test_insert_creates_section_when_section_style(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        doc.set("input:kb_layout", "us")
        result = doc.serialize()
        assert "input {\n" in result
        assert "    kb_layout = us\n" in result

    def test_insert_uses_inline_when_inline_style(self):
        doc = parse_string("general:gaps_in = 5\n")
        doc.set("general:gaps_out", "10")
        result = doc.serialize()
        assert "general:gaps_out = 10\n" in result
        # Should NOT create a section block
        assert "{" not in result

    def test_insert_top_level(self):
        doc = parse_string("key = value\n")
        doc.set("new_key", "new_value")
        assert "new_key = new_value\n" in doc.serialize()

    def test_update_keyword(self):
        doc = parse_string("monitor = DP-2, 1920x1080, 0x0, 1\n")
        doc.set("monitor", "DP-1, 2560x1440, 0x0, 1")
        assert doc.get("monitor") == "DP-1, 2560x1440, 0x0, 1"
        assert "monitor = DP-1, 2560x1440, 0x0, 1\n" in doc.serialize()

    def test_update_keyword_preserves_inline_comment(self):
        doc = parse_string("bind = SUPER, P, pseudo # dwindle\n")
        doc.set("bind", "SUPER, P, togglesplit")
        assert doc.serialize() == "bind = SUPER, P, togglesplit # dwindle\n"

    def test_update_keyword_in_section(self):
        text = "animations {\n    animation = windows, 1, 3, default\n}\n"
        doc = parse_string(text)
        doc.set("animations:animation", "windows, 1, 7, myBezier")
        assert doc.get("animations:animation") == "windows, 1, 7, myBezier"
        assert "    animation = windows, 1, 7, myBezier\n" in doc.serialize()


class TestRemove:
    def test_remove_existing(self):
        doc = parse_string("a = 1\nb = 2\nc = 3\n")
        doc.remove("b")
        result = doc.serialize()
        assert "a = 1\n" in result
        assert "b = 2" not in result
        assert "c = 3\n" in result

    def test_remove_all_occurrences(self):
        doc = parse_string("key = first\nkey = second\n")
        doc.remove("key")
        assert doc.serialize() == ""

    def test_remove_nonexistent_is_noop(self):
        text = "key = value\n"
        doc = parse_string(text)
        doc.remove("nonexistent")
        assert doc.serialize() == text

    def test_remove_keyword(self):
        doc = parse_string(
            "bind = SUPER, Q, killactive,\nbind = SUPER, Return, exec, kitty\nkey = value\n"
        )
        doc.remove("bind")
        result = doc.serialize()
        assert "bind" not in result
        assert "key = value\n" in result

    def test_remove_keyword_in_section(self):
        doc = parse_string("animations {\n    animation = windows, 1, 3, default\n}\n")
        doc.remove("animations:animation")
        assert doc.find("animations:animation") is None
        assert doc.serialize() == "animations {\n}\n"

    def test_remove_keyword_in_section_by_bare_key(self):
        doc = parse_string("animations {\n    animation = windows, 1, 3, default\n}\n")
        doc.remove("animation")
        assert doc.find("animation") is None
        assert doc.serialize() == "animations {\n}\n"

    def test_remove_in_section(self):
        doc = parse_string("general {\n    gaps_in = 5\n    gaps_out = 10\n}\n")
        doc.remove("general:gaps_in")
        result = doc.serialize()
        assert "gaps_in" not in result
        assert "gaps_out = 10" in result


class TestRemoveWhere:
    def test_remove_matching_keywords(self):
        doc = parse_string("bind = SUPER, Q, killactive,\nbind = SUPER, Return, exec, kitty\n")
        doc.remove_where("bind", lambda v: "killactive" in v)
        result = doc.serialize()
        assert "killactive" not in result
        assert "exec, kitty" in result

    def test_remove_animation_by_name(self):
        doc = parse_string("animation = windows, 1, 3, default\nanimation = fade, 1, 7, default\n")
        doc.remove_where("animation", lambda v: v.split(",")[0].strip() == "windows")
        result = doc.serialize()
        assert "windows" not in result
        assert "fade" in result

    def test_no_match_is_noop(self):
        text = "bind = SUPER, Q, killactive,\n"
        doc = parse_string(text)
        doc.remove_where("bind", lambda v: "nonexistent" in v)
        assert doc.serialize() == text


class TestAppend:
    def test_append_after_existing(self):
        doc = parse_string("bind = SUPER, Q, killactive,\n")
        doc.append("bind", "SUPER, Return, exec, kitty")
        result = doc.serialize()
        assert "killactive" in result
        assert "exec, kitty" in result
        # New line should come after existing
        assert result.index("killactive") < result.index("exec, kitty")

    def test_append_when_none_exist(self):
        doc = parse_string("key = value\n")
        doc.append("bind", "SUPER, Q, killactive,")
        assert "bind = SUPER, Q, killactive,\n" in doc.serialize()

    def test_append_preserves_indentation(self):
        doc = parse_string("animations {\n    animation = windows, 1, 3, default\n}\n")
        doc.append("animation", "fade, 1, 7, default")
        result = doc.serialize()
        # Should match the indentation of existing animation line
        assert "    animation = fade, 1, 7, default\n" in result


# ---------------------------------------------------------------------------
# Dirty tracking
# ---------------------------------------------------------------------------


class TestDirtyTracking:
    def test_fresh_document_not_dirty(self):
        doc = parse_string("key = value\n")
        assert doc.dirty is False

    def test_set_marks_dirty(self):
        doc = parse_string("key = value\n")
        doc.set("key", "new")
        assert doc.dirty is True

    def test_remove_marks_dirty(self):
        doc = parse_string("key = value\n")
        doc.remove("key")
        assert doc.dirty is True

    def test_remove_noop_not_dirty(self):
        doc = parse_string("key = value\n")
        doc.remove("nonexistent")
        assert doc.dirty is False

    def test_append_marks_dirty(self):
        doc = parse_string("")
        doc.append("bind", "SUPER, Q, killactive,")
        assert doc.dirty is True

    def test_dirty_files_empty_when_clean(self):
        doc = parse_string("key = value\n")
        assert doc.dirty_files() == []

    def test_dirty_files_lists_modified(self, tmp_path):
        a = tmp_path / "a.conf"
        b = tmp_path / "b.conf"
        a.write_text("x = 1\n")
        b.write_text("y = 2\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {a}\nsource = {b}\n")

        doc = load(main)
        doc.set("y", "99")
        assert doc.dirty_files() == [b.resolve()]

    def test_save_clears_dirty(self, tmp_path):
        doc = parse_string("key = value\n")
        doc.set("key", "new")
        assert doc.dirty is True
        doc.save(tmp_path / "out.conf")
        assert doc.dirty is False


# ---------------------------------------------------------------------------
# Variable mutation API
# ---------------------------------------------------------------------------


class TestSetVariable:
    def test_set_new_variable(self):
        doc = parse_string("key = value\n")
        doc.set_variable("mainMod", "SUPER")
        assert doc.variables["mainMod"] == "SUPER"
        assert "$mainMod = SUPER\n" in doc.serialize()

    def test_update_existing_variable(self):
        doc = parse_string("$mainMod = SUPER\nkey = value\n")
        doc.set_variable("mainMod", "ALT")
        assert doc.variables["mainMod"] == "ALT"
        assert "$mainMod = ALT\n" in doc.serialize()
        assert "SUPER" not in doc.serialize()

    def test_insert_after_existing_variables(self):
        doc = parse_string("$a = 1\n$b = 2\nkey = value\n")
        doc.set_variable("c", "3")
        result = doc.serialize()
        # $c should be after $b but before key
        assert result.index("$c") > result.index("$b")
        assert result.index("$c") < result.index("key")

    def test_insert_at_top_when_no_variables(self):
        doc = parse_string("key = value\n")
        doc.set_variable("x", "42")
        result = doc.serialize()
        assert result.startswith("$x = 42\n")

    def test_expand_uses_updated_variable(self):
        doc = parse_string("$mainMod = SUPER\n")
        doc.set_variable("mainMod", "ALT")
        assert doc.expand("$mainMod + Q") == "ALT + Q"

    def test_update_last_occurrence(self):
        doc = parse_string("$x = 1\n$x = 2\n")
        doc.set_variable("x", "3")
        result = doc.serialize()
        assert "$x = 1\n" in result
        assert "$x = 3\n" in result
        assert "$x = 2" not in result


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


class TestCopy:
    CONFIG = """\
general {
    gaps_in = 5
}

bind = SUPER, Q, killactive
"""

    def test_copy_is_independent(self):
        doc = parse_string(self.CONFIG)
        clone = doc.copy()

        # Mutate the clone
        clone.set("general:gaps_in", 20)

        # Original should be unchanged
        assert doc.get("general:gaps_in") == "5"
        assert clone.get("general:gaps_in") == "20"

    def test_copy_preserves_content(self):
        doc = parse_string(self.CONFIG)
        clone = doc.copy()

        assert clone.serialize() == doc.serialize()
        assert clone.get("general:gaps_in") == "5"
        assert len(clone.find_all("bind")) == 1

    def test_copy_dirty_state(self):
        doc = parse_string(self.CONFIG)
        assert not doc.dirty

        clone = doc.copy()
        assert not clone.dirty

        clone.set("general:gaps_in", 10)
        assert clone.dirty
        assert not doc.dirty

    def test_copy_variables(self):
        doc = parse_string("$mainMod = SUPER\nbind = $mainMod, Q, killactive\n")
        clone = doc.copy()

        clone.set_variable("mainMod", "ALT")
        assert clone.variables["mainMod"] == "ALT"
        assert doc.variables["mainMod"] == "SUPER"
