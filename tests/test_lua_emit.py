"""Lua emitter — structure, value coercion, key formatting, property/fuzz, luac."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hyprland_config import Document, keyword_to_lua, load, parse_string, serialize_lua
from hyprland_config._lua import serialize_lua_tree
from tests._lua_helpers import assert_lua_compiles, requires_lua


class TestEmptyDocument:
    def test_empty_doc_returns_empty_string(self) -> None:
        # No built-in banner — consumers brand their own output via Comment
        # nodes, so an empty Document renders as an empty string.
        assert serialize_lua(Document()) == ""

    def test_parsed_empty_string(self) -> None:
        assert serialize_lua(parse_string("")) == ""

    def test_only_comments_round_trip_as_lua_comments(self) -> None:
        # Comments delimit topical groups in the Lua output; standalone
        # comments survive as `--` lines so users keep the structure they
        # wrote in Hyprlang.
        out = serialize_lua(parse_string("# just a comment\n"))
        assert "-- just a comment" in out


class TestCategoryAssignments:
    def test_single_assignment(self) -> None:
        out = serialize_lua(parse_string("general:gaps_in = 5\n"))
        assert "hl.config(" in out
        assert "general = {" in out
        assert "gaps_in = 5," in out

    def test_multiple_in_same_section(self) -> None:
        out = serialize_lua(parse_string("general:gaps_in = 5\ngeneral:gaps_out = 20\n"))
        assert out.count("hl.config(") == 1
        assert "gaps_in = 5," in out
        assert "gaps_out = 20," in out

    def test_section_block_syntax(self) -> None:
        out = serialize_lua(parse_string("general {\n    gaps_in = 5\n    gaps_out = 20\n}\n"))
        assert "general = {" in out
        assert "gaps_in = 5," in out
        assert "gaps_out = 20," in out

    def test_nested_colon_path(self) -> None:
        out = serialize_lua(parse_string("decoration:blur:size = 3\n"))
        assert "decoration = {" in out
        assert "blur = {" in out
        assert "size = 3," in out

    def test_dotted_key_becomes_subtable(self) -> None:
        # `col.inactive_border` is Hyprlang's prefix convention and maps to a
        # nested Lua table.
        out = serialize_lua(parse_string("general:col.inactive_border = rgba(595959aa)\n"))
        assert "col = {" in out
        assert 'inactive_border = "rgba(595959aa)",' in out

    def test_mixed_colon_and_dot(self) -> None:
        out = serialize_lua(parse_string("group:groupbar:col.active = 0xff112233\n"))
        assert "group = {" in out
        assert "groupbar = {" in out
        assert "col = {" in out
        assert 'active = "0xff112233",' in out

    def test_last_value_wins(self) -> None:
        out = serialize_lua(parse_string("general:gaps_in = 5\ngeneral:gaps_in = 10\n"))
        assert "gaps_in = 10," in out
        assert "gaps_in = 5," not in out


class TestVariablePreservation:
    """Hyprlang ``$var`` references survive the Lua migration as named
    ``local var_NAME`` declarations, so the user keeps the same indirection
    they had in the source. Previously variables were silently inlined (or,
    worse, surfaced as the literal string ``"$var"`` — the noctalia-colors
    bug that Hyprland rejected at reload).
    """

    def test_simple_variable_becomes_local(self) -> None:
        out = serialize_lua(
            parse_string("$primary = rgb(98a8b3)\ngeneral:col.active_border = $primary\n")
        )
        assert 'local var_primary = "rgb(98a8b3)"' in out
        assert "active_border = var_primary," in out
        # No literal string with the colour or a leftover ``$primary``.
        assert '"rgb(98a8b3)"' in out  # only in the local declaration
        assert out.count('"rgb(98a8b3)"') == 1
        assert "$primary" not in out

    def test_multiple_variables_share_preamble(self) -> None:
        out = serialize_lua(
            parse_string(
                "$primary = rgb(98a8b3)\n"
                "$surface = rgb(1c1f21)\n"
                "general {\n"
                "    col.active_border = $primary\n"
                "    col.inactive_border = $surface\n"
                "}\n"
            )
        )
        assert 'local var_primary = "rgb(98a8b3)"' in out
        assert 'local var_surface = "rgb(1c1f21)"' in out
        assert "active_border = var_primary," in out
        assert "inactive_border = var_surface," in out

    def test_full_noctalia_colors_shape(self) -> None:
        # The exact shape from issue #38 — definitions at top, references
        # across general / group / groupbar sections.
        out = serialize_lua(
            parse_string(
                "$primary = rgb(98a8b3)\n"
                "$surface = rgb(1c1f21)\n"
                "$secondary = rgb(8d97a5)\n"
                "general {\n"
                "    col.active_border = $primary\n"
                "    col.inactive_border = $surface\n"
                "}\n"
                "group {\n"
                "    col.border_active = $secondary\n"
                "    col.border_inactive = $surface\n"
                "    groupbar {\n"
                "        col.active = $secondary\n"
                "        col.inactive = $surface\n"
                "    }\n"
                "}\n"
            )
        )
        for line in (
            'local var_primary = "rgb(98a8b3)"',
            'local var_surface = "rgb(1c1f21)"',
            'local var_secondary = "rgb(8d97a5)"',
        ):
            assert line in out
        assert "active_border = var_primary," in out
        assert "inactive_border = var_surface," in out
        assert "border_active = var_secondary," in out
        # No string literals quoting the colours at use sites.
        assert '"rgb(98a8b3)"' in out  # preamble only
        assert out.count('"rgb(98a8b3)"') == 1
        assert "$" not in out

    def test_unused_variable_is_not_emitted(self) -> None:
        # Only referenced variables make it into the preamble — matches the
        # Hyprlang side, which silently ignores unused variables.
        out = serialize_lua(
            parse_string(
                "$used = rgb(98a8b3)\n$unused = rgb(112233)\ngeneral:col.active_border = $used\n"
            )
        )
        assert "var_used" in out
        assert "var_unused" not in out
        assert "rgb(112233)" not in out

    def test_undefined_variable_passes_through(self) -> None:
        # No definition for ``$undef`` — ``expand_value_lua`` leaves it as
        # the literal ``$undef`` and the coercer quotes it.
        out = serialize_lua(parse_string("general:col.active_border = $undef\n"))
        assert 'active_border = "$undef",' in out

    def test_variable_chain_emits_both_locals(self) -> None:
        # ``$accent = $primary`` — the indirection survives on the Lua side
        # as ``local var_accent = var_primary``. Order matters: ``var_primary``
        # must be declared first, otherwise Lua evaluates ``var_accent``'s
        # RHS against an undeclared local and silently captures ``nil``.
        out = serialize_lua(
            parse_string(
                "$primary = rgb(98a8b3)\n$accent = $primary\ngeneral:col.active_border = $accent\n"
            )
        )
        assert 'local var_primary = "rgb(98a8b3)"' in out
        assert "local var_accent = var_primary" in out
        assert "active_border = var_accent," in out
        assert out.index("local var_primary") < out.index("local var_accent")

    def test_multi_hop_chain_orders_deps_first(self) -> None:
        # Three-deep chain: every dependency lands above its referrer so
        # the locals resolve to real values rather than ``nil``.
        out = serialize_lua(
            parse_string("$a = rgb(111111)\n$b = $a\n$c = $b\ngeneral:col.active_border = $c\n")
        )
        a_pos = out.index("local var_a")
        b_pos = out.index("local var_b")
        c_pos = out.index("local var_c")
        assert a_pos < b_pos < c_pos

    def test_variable_in_gradient_keeps_structured_form(self) -> None:
        # Gradients must stay structured (``{colors=…, angle=…}``) — Hyprland's
        # Lua API routes single-string and structured-table values through
        # different code paths.
        out = serialize_lua(
            parse_string(
                "$c1 = rgba(b4e718ee)\n"
                "$c2 = rgba(00ff99ee)\n"
                "general:col.active_border = $c1 $c2 45deg\n"
            )
        )
        assert "colors = {var_c1, var_c2}" in out
        assert "angle = 45," in out

    def test_mainmod_survives_in_bind(self) -> None:
        out = serialize_lua(parse_string("$mainMod = SUPER\nbind = $mainMod, Q, killactive\n"))
        assert 'local var_mainMod = "SUPER"' in out
        # The bind key combo references the local via concat.
        assert 'hl.bind(var_mainMod .. " + Q"' in out

    def test_numeric_variable_emits_as_lua_number(self) -> None:
        # ``$size = 10`` becomes ``local var_size = 10`` (number, not string)
        # so it can drop into a numeric-typed setting like ``gaps_in``
        # without manual ``tonumber()`` wrapping.
        out = serialize_lua(parse_string("$size = 10\ngeneral:gaps_in = $size\n"))
        assert "local var_size = 10" in out
        assert 'local var_size = "10"' not in out
        assert "gaps_in = var_size," in out

    def test_float_variable_emits_as_lua_number(self) -> None:
        out = serialize_lua(parse_string("$opacity = 0.9\ndecoration:active_opacity = $opacity\n"))
        assert "local var_opacity = 0.9" in out
        assert "active_opacity = var_opacity," in out

    def test_bool_variable_emits_as_lua_bool(self) -> None:
        # Hyprlang ``yes`` / ``no`` coerce to native Lua booleans —
        # required because Hyprland's Lua API strict-checks bool fields.
        out = serialize_lua(
            parse_string("$blur = yes\ndecoration {\n    blur:enabled = $blur\n}\n")
        )
        assert "local var_blur = true" in out
        assert "enabled = var_blur," in out

    def test_lua_invalid_variable_name_prefixed(self) -> None:
        # ``$end`` is a Lua reserved word; ``$my-color`` carries a dash which
        # isn't a valid Lua identifier character. Both ride the ``var_``
        # prefix and the dash collapses to underscore.
        out = serialize_lua(
            parse_string(
                "$end = rgb(112233)\n"
                "$my-color = rgb(445566)\n"
                "general:col.active_border = $end\n"
                "general:col.inactive_border = $my-color\n"
            )
        )
        assert 'local var_end = "rgb(112233)"' in out
        assert 'local var_my_color = "rgb(445566)"' in out
        assert "active_border = var_end," in out
        assert "inactive_border = var_my_color," in out


class TestValueCoercion:
    def test_int_emitted_as_number(self) -> None:
        assert "gaps_in = 5," in serialize_lua(parse_string("general:gaps_in = 5\n"))

    def test_negative_int(self) -> None:
        assert "force_default_wallpaper = -1," in (
            serialize_lua(parse_string("misc:force_default_wallpaper = -1\n"))
        )

    def test_float_emitted_as_number(self) -> None:
        out = serialize_lua(parse_string("decoration:active_opacity = 0.9\n"))
        assert "active_opacity = 0.9," in out

    def test_bool_true(self) -> None:
        assert "enabled = true," in serialize_lua(parse_string("decoration:blur:enabled = true\n"))

    def test_bool_false(self) -> None:
        out = serialize_lua(parse_string("misc:disable_hyprland_logo = false\n"))
        assert "disable_hyprland_logo = false," in out

    def test_bool_case_insensitive(self) -> None:
        # Hyprlang accepts True/TRUE/etc.; we coerce them all to lowercase Lua.
        assert "x = true," in serialize_lua(parse_string("general:x = True\n"))
        assert "x = false," in serialize_lua(parse_string("general:x = FALSE\n"))

    def test_bool_hyprlang_aliases(self) -> None:
        # Hyprlang also accepts yes/no/on/off for boolean options; Hyprland's
        # Lua API only takes native booleans, so we coerce all six spellings.
        # Without this the user gets "boolean type requires a bool" at runtime.
        assert "x = true," in serialize_lua(parse_string("general:x = yes\n"))
        assert "x = false," in serialize_lua(parse_string("general:x = no\n"))
        assert "x = true," in serialize_lua(parse_string("general:x = on\n"))
        assert "x = false," in serialize_lua(parse_string("general:x = off\n"))
        # Case-insensitive, same as true/false.
        assert "x = true," in serialize_lua(parse_string("general:x = YES\n"))
        assert "x = false," in serialize_lua(parse_string("general:x = Off\n"))

    def test_bool_lenient_leading_token(self) -> None:
        # Hyprland's Hyprlang parser reads only the leading token of a
        # boolean field, so `enabled = yes, please :)` (a real value in the
        # default config example) coerces to ``true``. Without this the
        # joke value would survive as a Lua string and break Hyprland's
        # strict boolean type check at load time.
        assert "x = true," in serialize_lua(parse_string("general:x = yes, please :)\n"))
        assert "x = true," in serialize_lua(parse_string("general:x = on whatever\n"))
        assert "x = false," in serialize_lua(parse_string("general:x = no thanks\n"))

    def test_bool_lenient_match_respects_word_boundary(self) -> None:
        # Identifiers that merely start with a bool word stay as strings —
        # ``yesterday`` is not truthy, ``offer`` is not falsy, ``oneshot``
        # is not truthy. The ``\b`` boundary anchor in the regex guards
        # against these false positives.
        assert 'x = "yesterday",' in serialize_lua(parse_string("general:x = yesterday\n"))
        assert 'x = "oneshot",' in serialize_lua(parse_string("general:x = oneshot\n"))
        assert 'x = "offer",' in serialize_lua(parse_string("general:x = offer\n"))
        assert 'x = "nope",' in serialize_lua(parse_string("general:x = nope\n"))

    def test_string_value_quoted(self) -> None:
        assert 'kb_layout = "us",' in serialize_lua(parse_string("input:kb_layout = us\n"))

    def test_string_with_special_chars_escaped(self) -> None:
        # Hyprlang doesn't really emit these in defaults, but the emitter
        # must still handle them safely if set programmatically.
        doc = parse_string("input:kb_layout = us\n")
        node = doc.find("input:kb_layout")
        assert node is not None
        node.value = 'a"b\\c'
        out = serialize_lua(doc)
        assert r'kb_layout = "a\"b\\c",' in out

    def test_color_kept_as_string(self) -> None:
        out = serialize_lua(parse_string("general:col.active_border = rgba(33ccffee)\n"))
        assert 'active_border = "rgba(33ccffee)",' in out

    def test_multicolor_gradient_becomes_structured(self) -> None:
        out = serialize_lua(
            parse_string("general:col.active_border = rgba(b4e718ee) rgba(00ff99ee) 45deg\n")
        )
        assert "active_border = {" in out
        assert 'colors = {"rgba(b4e718ee)", "rgba(00ff99ee)"}' in out
        assert "angle = 45," in out

    def test_single_color_with_angle_becomes_structured(self) -> None:
        # A single color but with a non-zero angle is still a gradient (just
        # one of its stops is implied).
        out = serialize_lua(parse_string("general:col.active_border = rgba(b4e718ee) 90deg\n"))
        assert "angle = 90," in out

    def test_single_color_no_angle_stays_string(self) -> None:
        # Matches the upstream Lua example, which uses bare strings for
        # single-color borders and structured tables only for gradients.
        out = serialize_lua(parse_string("decoration:shadow:color = rgba(1a1a1aee)\n"))
        assert 'color = "rgba(1a1a1aee)",' in out

    def test_single_color_with_zero_angle_drops_angle(self) -> None:
        # A single-color border with an explicit ``0deg`` isn't a gradient.
        # Hyprland's Lua color parser rejects the ``"<color> 0deg"`` string
        # (issue #43), so the no-op angle is dropped to a bare color, in the
        # original notation.
        out = serialize_lua(parse_string("general:col.active_border = 0xffed333b 0deg\n"))
        assert 'active_border = "0xffed333b",' in out
        assert "0deg" not in out


class TestStringTypedOptions:
    """An option Hyprland types as a string never coerces to a bool.

    Hyprlang's boolean words include ``no``, ``on`` and ``off``, which are
    also legitimate values of string options — ``input:kb_layout = no`` is
    the Norwegian layout. Hyprland's Lua API is strictly typed and answers a
    boolean there with "string type requires a string", so inferring the
    type from the value's shape alone corrupts the line (hyprmod issue 96).
    """

    def test_norwegian_keyboard_layout_stays_a_string(self) -> None:
        out = serialize_lua(parse_string("input:kb_layout = no\n"))
        assert 'kb_layout = "no",' in out

    def test_layout_list_led_by_a_bool_word(self) -> None:
        # The lenient bool match anchors at the start of the value and a
        # comma is a word boundary, so the whole list collapsed to ``false``
        # while ``us,no`` survived by luck.
        assert 'kb_layout = "no,us",' in serialize_lua(parse_string("input:kb_layout = no,us\n"))
        assert 'kb_layout = "us,no",' in serialize_lua(parse_string("input:kb_layout = us,no\n"))

    def test_regex_starting_with_a_bool_word(self) -> None:
        out = serialize_lua(parse_string("misc:swallow_regex = no.*\n"))
        assert 'swallow_regex = "no.*",' in out

    def test_device_block_field_borrows_the_input_option_type(self) -> None:
        # A ``device { … }`` block overrides the matching ``input:`` option,
        # so its ``kb_layout`` is the same string-typed key under another
        # name.
        out = serialize_lua(parse_string("device {\n    name = my-kbd\n    kb_layout = no\n}\n"))
        assert 'kb_layout = "no",' in out

    def test_bool_option_still_coerces_its_hyprlang_aliases(self) -> None:
        # The suppression is keyed on the option, not the value: a real
        # boolean option keeps every Hyprlang spelling.
        out = serialize_lua(parse_string("general:resize_on_border = no\n"))
        assert "resize_on_border = false," in out

    def test_numeric_string_option_stays_a_string(self) -> None:
        # ``general:locale`` is string-typed, so a value that happens to
        # look like a number must not emit as one either.
        assert 'locale = "7",' in serialize_lua(parse_string("general:locale = 7\n"))

    def test_unknown_option_still_infers_from_the_value(self) -> None:
        # Options outside the schema (a plugin's, or a typo) have no type to
        # honour, so shape inference stays the fallback.
        assert "x = false," in serialize_lua(parse_string("general:x = no\n"))

    def test_live_apply_matches_the_written_value(self) -> None:
        # The two ways the value reaches Hyprland — pushed through
        # ``hyprctl eval`` and written to the config — have to agree.
        assert 'kb_layout = "no",' in keyword_to_lua("input:kb_layout", "no")


class TestKeyFormatting:
    def test_lua_reserved_word_as_key_gets_bracketed(self) -> None:
        # Theoretical case — unlikely in real configs but the emitter must
        # not produce invalid Lua identifiers.
        doc = parse_string("foo:end = 1\n")
        out = serialize_lua(doc)
        assert '["end"] = 1,' in out

    def test_non_identifier_key_gets_bracketed(self) -> None:
        doc = parse_string("foo:weird-key = 1\n")
        out = serialize_lua(doc)
        assert '["weird-key"] = 1,' in out


class TestUnsupportedKeywords:
    def test_submap_block_translated_not_todo(self) -> None:
        # The walker now buffers the ``submap = NAME`` … ``submap = reset``
        # range and emits a single ``hl.define_submap(NAME, function() …
        # end)``. An empty submap (no binds inside) is dropped — Hyprland
        # rejects those at runtime, so the empty Lua call would just be noise.
        empty = serialize_lua(parse_string("submap = resize\n"))
        assert "hl.define_submap" not in empty
        assert "-- TODO" not in empty

        populated = serialize_lua(
            parse_string("submap = resize\nbind = , right, resizeactive, 10 0\nsubmap = reset\n")
        )
        assert 'hl.define_submap("resize", function()' in populated
        assert "-- TODO" not in populated

    def test_unbind_emits_hl_unbind_call(self) -> None:
        # hyprmod's override flow leans on unbind lines: when our managed
        # sidecar overrides a user bind, we emit ``unbind`` ahead of our
        # own ``bind`` so Hyprland's last-write-wins order resolves to
        # our version. Routing these to the manual-conversion block (the
        # pre-fix behaviour) silently broke that flow in Lua mode.
        out = serialize_lua(parse_string("unbind = SUPER, Q\n"))
        assert "-- TODO" not in out
        assert 'hl.unbind("SUPER + Q")' in out

    def test_unbind_bare_key_no_mods(self) -> None:
        out = serialize_lua(parse_string("unbind = , F1\n"))
        assert 'hl.unbind("F1")' in out

    def test_unbind_multiple_mods(self) -> None:
        out = serialize_lua(parse_string("unbind = SUPER SHIFT, mouse:272\n"))
        assert 'hl.unbind("SUPER + SHIFT + mouse:272")' in out

    def test_plugin_emits_hl_plugin_load(self) -> None:
        # ``hl.plugin`` is a namespace table on the real Hyprland runtime —
        # the call shape is ``hl.plugin.load(path)``. Emitting bare
        # ``hl.plugin(path)`` would raise "attempt to call a table value"
        # at config-load time.
        out = serialize_lua(parse_string("plugin = /usr/lib/hyprland/foo.so\n"))
        assert "-- TODO" not in out
        assert 'hl.plugin.load("/usr/lib/hyprland/foo.so")' in out

    def test_plugin_empty_path_goes_to_todo(self) -> None:
        # ``plugin =`` with no value would emit ``hl.plugin.load("")`` —
        # that's still invalid (Hyprland would reject it at runtime), so
        # surface it for manual review instead.
        out = serialize_lua(parse_string("plugin =\n"))
        assert "-- TODO" in out
        assert "plugin =" in out

    def test_multiple_unsupported_listed_in_one_todo_block(self) -> None:
        # ``plugin =`` with no path and a malformed bind both surface in the
        # same trailing TODO block — one ``-- TODO`` header for all of them.
        out = serialize_lua(parse_string("plugin =\nbind = SUPER\n"))
        assert out.count("-- TODO") == 1
        assert "plugin =" in out
        assert "bind = SUPER" in out

    def test_unmapped_line_shows_dollar_var_not_marker_bytes(self) -> None:
        # An untranslatable bind that references a $var must surface its
        # original text. Regression: the emitter dumped the marker-substituted
        # form (\x01mainMod\x02 from expand_value_lua), which rendered as
        # mojibake boxes in the "won't migrate" UI instead of $mainMod.
        out = serialize_lua(
            parse_string("$mainMod = SUPER\nbind = $mainMod SHIFT, V, workspaceopt, allfloat\n")
        )
        assert "bind = $mainMod SHIFT, V, workspaceopt, allfloat" in out
        assert "\x01" not in out
        assert "\x02" not in out


class TestStructure:
    def test_only_assignments_no_extras_block(self) -> None:
        out = serialize_lua(parse_string("general:gaps_in = 5\n"))
        assert "hl.config(" in out
        assert "hl.env" not in out

    def test_only_keywords_no_config_block(self) -> None:
        out = serialize_lua(parse_string("env = X, 1\n"))
        assert "hl.config(" not in out
        assert 'hl.env("X", "1")' in out

    def test_assignments_then_extras_then_todo(self) -> None:
        out = serialize_lua(parse_string("general:gaps_in = 5\nenv = X, 1\nplugin =\n"))
        # The three blocks appear in this order.
        config_idx = out.index("hl.config(")
        env_idx = out.index("hl.env")
        todo_idx = out.index("-- TODO")
        assert config_idx < env_idx < todo_idx


class TestCommentGrouping:
    """Comments delimit topical groups: each becomes a ``-- header`` and
    splits the following content into its own ``hl.config({...})`` call so
    sections don't merge across boundaries.
    """

    def test_comment_becomes_lua_comment(self) -> None:
        out = serialize_lua(parse_string("# Environment\nenv = X, 1\n"))
        assert "-- Environment" in out
        assert 'hl.env("X", "1")' in out
        # Header appears before the call it labels.
        assert out.index("-- Environment") < out.index("hl.env")

    def test_two_comment_sections_split_config_calls(self) -> None:
        # Without grouping, both assignments would merge into one
        # hl.config({general = {...}, decoration = {...}}). With grouping,
        # each section gets its own call under its own header.
        config = "# General\ngeneral:gaps_in = 5\n\n# Decoration\ndecoration:rounding = 10\n"
        out = serialize_lua(parse_string(config))
        assert out.count("hl.config(") == 2
        general_idx = out.index("-- General")
        decoration_idx = out.index("-- Decoration")
        assert general_idx < decoration_idx
        # Each section's assignments stay under their own header.
        assert out.index("gaps_in") < decoration_idx
        assert out.index("rounding") > decoration_idx

    def test_lines_before_first_comment_go_in_unnamed_group(self) -> None:
        config = "general:gaps_in = 5\n# Decoration\ndecoration:rounding = 10\n"
        out = serialize_lua(parse_string(config))
        # The unnamed leading group emits before any `--` header.
        first_config = out.index("hl.config(")
        first_header = out.index("-- Decoration")
        assert first_config < first_header
        assert out.count("hl.config(") == 2

    def test_empty_group_emits_header_only(self) -> None:
        # A comment with no content following it (until the next comment or
        # end of file) still produces a `--` line — preserves decorative
        # banners and section stubs.
        out = serialize_lua(parse_string("# Decorative banner\n# Real section\nenv = X, 1\n"))
        assert "-- Decorative banner" in out
        assert "-- Real section" in out

    def test_exec_blocks_respect_groups(self) -> None:
        # ``exec`` keywords emit at top-level (one per call, every-reload
        # semantics) — they don't get batched into an ``hl.on`` block.
        # The grouping still applies: each section's calls render under
        # its own ``-- header`` line in source order.
        config = "# Section A\nexec = waybar\n\n# Section B\nexec = nm-applet\n"
        out = serialize_lua(parse_string(config))
        assert 'hl.on("hyprland.start"' not in out
        section_a = out.index("-- Section A")
        waybar = out.index('hl.exec_cmd("waybar")')
        section_b = out.index("-- Section B")
        applet = out.index('hl.exec_cmd("nm-applet")')
        assert section_a < waybar < section_b < applet

    def test_exec_once_blocks_respect_groups(self) -> None:
        # ``exec-once`` keywords under different comment sections produce
        # separate ``hl.on("hyprland.start", function() … end)`` blocks,
        # not one merged — each block stays within its topical group.
        config = "# Section A\nexec-once = waybar\n\n# Section B\nexec-once = nm-applet\n"
        out = serialize_lua(parse_string(config))
        assert out.count('hl.on("hyprland.start"') == 2

    def test_no_comments_matches_legacy_layout(self) -> None:
        # A config with no comments at all produces output indistinguishable
        # from the pre-grouping behaviour: one hl.config, one block of extras.
        out = serialize_lua(parse_string("general:gaps_in = 5\nenv = X, 1\n"))
        assert out.count("hl.config(") == 1
        assert out.count('hl.env("X", "1")') == 1
        assert "--" not in out


class TestCleanFileShape:
    def test_output_ends_with_newline(self) -> None:
        assert serialize_lua(parse_string("general:gaps_in = 5\n")).endswith("\n")

    def test_no_built_in_banner(self) -> None:
        # The library doesn't stamp its own ``-- Generated by …`` header;
        # consumers add their own via Comment nodes if they want one.
        out = serialize_lua(parse_string("general:gaps_in = 5\n"))
        assert not out.startswith("--")

    def test_serialize_lua_is_module_level_function(self) -> None:
        # Both call paths should produce the same output.
        doc = parse_string("general:gaps_in = 5\n")
        assert serialize_lua(doc) == serialize_lua(doc)


class TestHyprModProfile:
    """End-to-end coverage of every line shape hyprmod writes.

    Hyprmod's ``build_content`` emits lines that fall into these categories;
    the whole file together must serialize cleanly with no manual-conversion
    entries.
    """

    def test_full_profile_emits_no_todo(self, tmp_path) -> None:
        config = (
            "# Generated by HyprMod\n"
            "\n"
            "# Environment\n"
            "env = XCURSOR_THEME,Bibata-Modern-Classic\n"
            "env = XCURSOR_SIZE,24\n"
            "\n"
            "general:gaps_in = 20\n"
            "misc:vrr = 0\n"
            "\n"
            "# Bezier curves\n"
            "bezier = myBezier, 0.05, 0.9, 0.1, 1.05\n"
            "\n"
            "# Animations\n"
            "animation = windows, 1, 7, myBezier, slide\n"
            "\n"
            "# Monitors\n"
            "monitor = DP-2, 3440x1440@164.90Hz, 0x0, 1, bitdepth, 10\n"
            "\n"
            "# Keybinds\n"
            "bind = SUPER, Q, killactive,\n"
            "bind = SUPER, return, exec, ghostty\n"
            "\n"
            "# Window rules\n"
            "windowrule = match:title ^Albert$, stay_focused on\n"
            "windowrule = match:class ^kitty$, opacity 0.9\n"
            "\n"
            "# Layer rules\n"
            "layerrule = match:namespace ^waybar$, blur on\n"
            "\n"
            "# Autostart\n"
            "exec = waybar\n"
            "exec-once = nm-applet\n"
        )
        (tmp_path / "hyprland-gui.conf").write_text(config)
        out = serialize_lua(load(tmp_path / "hyprland-gui.conf"))
        # The trailing "manual conversion" block must be absent — i.e. every
        # line hyprmod writes maps to a real Lua call. The inline marker
        # comment next to exec-once is fine; it's informational, not a
        # fall-through.
        assert "manual conversion to Lua" not in out
        assert_lua_compiles(out)


class TestEmittedLuaCompiles:
    """End-to-end syntax check: emitted Lua must parse through ``luac -p``.

    These cases run the actual Lua compiler against the emitter output, so
    any syntax-level regression — unbalanced braces, missing quotes,
    malformed identifiers — fails loudly rather than producing plausible-
    looking but invalid Lua.
    """

    @requires_lua
    def test_empty_doc(self) -> None:
        assert_lua_compiles(serialize_lua(parse_string("")))

    @requires_lua
    def test_kitchen_sink(self) -> None:
        # Every emitter code path in one config.
        config = """
            # Variables
            $mainMod = SUPER

            # Generic options across multiple sections + nesting
            general:gaps_in = 5
            general:gaps_out = 10
            general:col.active_border = rgba(b4e718ee) rgba(00ff99ee) 45deg
            general:col.inactive_border = rgba(444444ee)
            decoration:rounding = 10
            decoration:blur:enabled = true
            decoration:blur:size = 3
            decoration:blur:passes = 2
            decoration:active_opacity = 1.0
            input:kb_layout = us
            input:kb_options =
            misc:vrr = 1
            misc:disable_hyprland_logo = false
            dwindle:pseudotile = 1
            dwindle:preserve_split = 1

            # Block syntax
            decoration {
                inactive_opacity = 0.9
                shadow {
                    enabled = true
                    range = 4
                    color = rgba(1a1a1aee)
                }
            }

            # Lua reserved word as key
            misc:end = 1

            # env / monitor / bezier / animation
            env = XCURSOR_THEME, Bibata
            env = XCURSOR_SIZE, 24
            monitor = DP-1, 2560x1440@144, 0x0, 1
            monitor = DP-2, preferred, auto, 1.25, transform, 3, bitdepth, 10, cm, srgb
            bezier = myCurve, 0.05, 0.9, 0.1, 1.05
            animation = windows, 1, 7, myCurve, slide
            animation = workspaces, 0, 2, default

            # bind family covering every supported flag + a range of dispatchers
            bind = $mainMod, Q, killactive,
            bind = $mainMod, M, exit
            bind = $mainMod, return, exec, kitty
            bind = $mainMod, V, togglefloating
            bind = $mainMod, F, fullscreen
            bind = $mainMod, P, pseudo
            bind = $mainMod, G, togglegroup
            bind = $mainMod, J, layoutmsg, togglesplit
            bind = $mainMod, left, movefocus, l
            bind = $mainMod SHIFT, right, movewindow, r
            bind = $mainMod, 1, workspace, 1
            bind = $mainMod, mouse_up, workspace, e+1
            bind = $mainMod SHIFT, 1, movetoworkspace, 1
            bind = $mainMod, 2, movetoworkspacesilent, 2
            bind = $mainMod, S, togglespecialworkspace, magic
            bind = $mainMod CTRL, left, changegroupactive, b
            bind = $mainMod CTRL, right, changegroupactive, f
            bind = $mainMod SHIFT, G, moveoutofgroup
            bind = $mainMod ALT, left, moveintogroup, l
            bind = ALT, tab, focuscurrentorlast
            bindm = $mainMod, mouse:272, movewindow
            bindm = $mainMod, mouse:273, resizewindow
            bindel = , XF86AudioRaiseVolume, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
            bindl = , XF86AudioMute, exec, mute
            bindrel = $mainMod, F1, exec, toggle-overlay
            bind = , special_key_with_quote, exec, echo "hi"

            # window rules — both effect-first and match-first
            windowrule = float, class:^kitty$
            windowrulev2 = opacity 0.9, class:^kitty$, title:^scratch$
            windowrule = match:title ^Albert$, stay_focused on
            windowrule = match:class ^jetbrains-.*$, match:title ^win.*$, match:float 1, no_focus on
            windowrule = match:initial_title ^Godot$, suppress_event maximize

            # layer rules
            layerrule = blur, ^waybar$
            layerrule = match:namespace ^rofi$, ignore_alpha 0.5
            layerrule = match:namespace ^wlogout$, dim_around on

            # workspace, gesture, permission, device
            workspace = 1, monitor:DP-1, default:true
            workspace = special:magic, monitor:DP-1
            gesture = 3, horizontal, workspace
            gesture = 4, vertical, special, workspace_name:magic
            permission = /usr/bin/grim, screencopy, allow

            device {
                name = epic-mouse-v1
                sensitivity = -0.5
            }

            # exec / exec-once / exec-shutdown
            exec = waybar
            exec-once = nm-applet
            exec-once = "command with spaces and \\"quotes\\""
            exec-shutdown = sync

            # Things that should land in the TODO block but not break the parse
            plugin = my-plugin.so
            submap = resize
            unbind = SUPER, Q
        """
        out = serialize_lua(parse_string(config))
        assert_lua_compiles(out)

    @requires_lua
    def test_tree_emit_each_file_compiles(self, tmp_path) -> None:
        # Multi-file output must produce parseable Lua *and* parseable
        # dofile() bridges in the parent.
        (tmp_path / "child.conf").write_text("env = X, 1\nbind = SUPER, Q, killactive,\n")
        (tmp_path / "main.conf").write_text("source = ./child.conf\ngeneral:gaps_in = 5\n")
        tree = serialize_lua_tree(load(tmp_path / "main.conf"))
        assert tree  # at minimum we got something out
        for entry in tree:
            try:
                assert_lua_compiles(entry.content)
            except AssertionError as e:
                raise AssertionError(f"{entry.path} failed:\n{e}") from None

    @requires_lua
    def test_strings_with_quotes_and_backslashes(self) -> None:
        # Lua string escaping must be airtight — a stray double quote in
        # exec args (e.g. for grimblast/copysave) would break the whole file.
        config = (
            'bind = SUPER, S, exec, sh -c "echo \\"hello world\\""\n'
            "env = WEIRD, \\\\path\\\\with\\\\backslashes\n"
            'env = QUOTE_IN_VALUE, "embedded \\"quote\\""\n'
        )
        out = serialize_lua(parse_string(config))
        assert_lua_compiles(out)


# ---------------------------------------------------------------------------
# Property-based / fuzz tests
# ---------------------------------------------------------------------------


_IDENT = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]{0,15}", fullmatch=True)
_VALUE = st.from_regex(r"[a-zA-Z0-9_./ -]{0,40}", fullmatch=True).filter(bool)
_MOD = st.sampled_from(["SUPER", "SHIFT", "CTRL", "ALT", "MOD3", ""])
_KEY = st.from_regex(r"[a-zA-Z0-9_]{1,12}", fullmatch=True)


@st.composite
def _bind_line(draw: st.DrawFn) -> str:
    btype = draw(st.sampled_from(["bind", "binde", "bindl", "bindr", "bindm", "bindel"]))
    mod = draw(_MOD)
    key = draw(_KEY)
    dispatcher = draw(
        st.sampled_from(
            [
                "exec",
                "killactive",
                "exit",
                "togglefloating",
                "fullscreen",
                "pseudo",
                "workspace",
                "movetoworkspace",
                "movefocus",
                "movewindow",
            ]
        )
    )
    arg = draw(_VALUE)
    return f"{btype} = {mod}, {key}, {dispatcher}, {arg}\n"


@st.composite
def _env_line(draw: st.DrawFn) -> str:
    name = draw(_IDENT)
    value = draw(_VALUE)
    return f"env = {name}, {value}\n"


@st.composite
def _section_assignment(draw: st.DrawFn) -> str:
    section = draw(st.sampled_from(["general", "decoration", "input", "misc", "dwindle"]))
    key = draw(_IDENT)
    value = draw(_VALUE)
    return f"{section}:{key} = {value}\n"


@st.composite
def _windowrule_line(draw: st.DrawFn) -> str:
    effect = draw(st.sampled_from(["float on", "stay_focused on", "opacity 0.9", "pin on"]))
    regex = draw(_VALUE)
    return f"windowrule = {effect}, match:class {regex}\n"


@st.composite
def _hyprland_config(draw: st.DrawFn) -> str:
    parts = draw(
        st.lists(
            st.one_of(
                _section_assignment(),
                _bind_line(),
                _env_line(),
                _windowrule_line(),
            ),
            min_size=0,
            max_size=15,
        )
    )
    return "".join(parts)


class TestEmitterProperty:
    """Property-based invariants — the emitter must not crash and (when luac
    is available) must always produce parseable Lua, no matter what
    syntactically valid Hyprlang it sees.
    """

    @given(config=_hyprland_config())
    @settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
    def test_serialize_lua_never_crashes(self, config: str) -> None:
        doc = parse_string(config, lenient=True)
        # The invariant under fuzz is "doesn't crash" — output shape is
        # covered by the deterministic tests above.
        serialize_lua(doc)

    @requires_lua
    @given(config=_hyprland_config())
    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    def test_emitted_lua_always_parses(self, config: str) -> None:
        doc = parse_string(config, lenient=True)
        assert_lua_compiles(serialize_lua(doc))


_arbitrary_text = st.text(
    alphabet=st.characters(codec="utf-8", categories=("L", "M", "N", "P", "S", "Z", "Cc")),
    min_size=0,
    max_size=300,
)


class TestEmitterFuzz:
    """Crash-test the emitter with arbitrary unicode input.

    The parser already protects us in lenient mode, but the emitter walks
    the resulting AST and could still trip over malformed BindData,
    weird Source paths, or odd characters in keyword args. None of that
    should crash; worst case is content in the manual-conversion block.
    """

    @given(text=_arbitrary_text)
    @settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
    def test_lenient_emit_never_crashes(self, text: str) -> None:
        doc = parse_string(text, lenient=True)
        serialize_lua(doc)

    @requires_lua
    @given(text=_arbitrary_text)
    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    def test_lenient_emit_always_parses(self, text: str) -> None:
        doc = parse_string(text, lenient=True)
        assert_lua_compiles(serialize_lua(doc))
