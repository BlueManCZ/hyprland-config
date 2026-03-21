"""Integration tests: recursive operations and the flat dict API."""

from hyprland_config import Source, load, parse_to_dict

# ---------------------------------------------------------------------------
# Recursive operations across sourced documents
# ---------------------------------------------------------------------------


class TestRecursive:
    def _make_tree(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("general {\n    gaps_in = 5\n}\n")
        main = tmp_path / "main.conf"
        main.write_text(f"top_key = hello\nsource = {sub}\n")

        return load(main, follow_sources=True)

    def test_find_recursive_by_default(self, tmp_path):
        doc = self._make_tree(tmp_path)
        # sources_followed=True, so find() recurses by default
        result = doc.find("general:gaps_in")
        assert result is not None
        assert result.value == "5"
        # Can explicitly disable recursion
        assert doc.find("general:gaps_in", recursive=False) is None

    def test_find_all_recursive_by_default(self, tmp_path):
        doc = self._make_tree(tmp_path)
        assert len(doc.find_all("general:gaps_in")) == 1
        assert len(doc.find_all("general:gaps_in", recursive=False)) == 0

    def test_set_recursive_updates_sub_document(self, tmp_path):
        doc = self._make_tree(tmp_path)
        doc.set("general:gaps_in", "20")

        # The sub-document should be modified
        source_node = doc.lines[1]
        assert isinstance(source_node, Source)
        sub_doc = source_node.documents[0]
        node = sub_doc.find("general:gaps_in")
        assert node is not None and node.value == "20"
        assert sub_doc.dirty is True
        # Root should NOT be dirty
        assert doc.dirty is False

    def test_set_recursive_inserts_in_root_when_not_found(self, tmp_path):
        doc = self._make_tree(tmp_path)
        doc.set("new_key", "new_value")
        node = doc.find("new_key")
        assert node is not None and node.value == "new_value"
        assert doc.dirty is True

    def test_remove_recursive(self, tmp_path):
        doc = self._make_tree(tmp_path)
        doc.remove("general:gaps_in")
        source_node = doc.lines[1]
        assert isinstance(source_node, Source)
        sub_doc = source_node.documents[0]
        assert sub_doc.find("general:gaps_in") is None
        assert sub_doc.dirty is True

    def test_append_recursive(self, tmp_path):
        binds = tmp_path / "binds.conf"
        binds.write_text("bind = SUPER, Q, killactive,\n")
        main = tmp_path / "main.conf"
        main.write_text(f"key = value\nsource = {binds}\n")

        doc = load(main, follow_sources=True)
        doc.append("bind", "SUPER, Return, exec, kitty")

        source_node = doc.lines[1]
        assert isinstance(source_node, Source)
        binds_doc = source_node.documents[0]
        assert len(binds_doc.find_all("bind")) == 2
        assert binds_doc.dirty is True
        assert doc.dirty is False

    def test_find_respects_source_position(self, tmp_path):
        """Root value after source directive should win over sourced value."""
        sub = tmp_path / "sub.conf"
        sub.write_text("key = from_sub\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\nkey = from_root\n")

        doc = load(main, follow_sources=True)
        # Root's key=from_root comes after source, so it should win
        node = doc.find("key")
        assert node is not None and node.value == "from_root"

    def test_find_sourced_wins_when_after_root(self, tmp_path):
        """Sourced value should win when source directive comes after root value."""
        sub = tmp_path / "sub.conf"
        sub.write_text("key = from_sub\n")
        main = tmp_path / "main.conf"
        main.write_text(f"key = from_root\nsource = {sub}\n")

        doc = load(main, follow_sources=True)
        # Source comes after key=from_root, so sub's value should win
        node = doc.find("key")
        assert node is not None and node.value == "from_sub"


# ---------------------------------------------------------------------------
# parse_to_dict (simple dict API)
# ---------------------------------------------------------------------------


class TestParseToDictAPI:
    def test_flat_file(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("general:gaps_in = 5\ngeneral:gaps_out = 10\n")

        result = parse_to_dict(conf)
        assert result["general:gaps_in"] == "5"
        assert result["general:gaps_out"] == "10"

    def test_variable_expansion(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("$myVar = hello\nkey = $myVar world\n")

        result = parse_to_dict(conf)
        assert result["key"] == "hello world"

    def test_section_keys(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("general {\n    gaps_in = 5\n}\n")

        result = parse_to_dict(conf)
        assert result["general:gaps_in"] == "5"

    def test_source_following(self, tmp_path):
        main = tmp_path / "main.conf"
        sub = tmp_path / "sub.conf"
        sub.write_text("imported_key = imported_value\n")
        main.write_text(f"source = {sub}\nlocal_key = local_value\n")

        result = parse_to_dict(main)
        assert result["local_key"] == "local_value"
        assert result["imported_key"] == "imported_value"

    def test_repeated_keywords_become_list(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text(
            "bind = SUPER, Q, killactive,\n"
            "bind = SUPER, Return, exec, kitty\n"
            "bind = SUPER, V, togglefloating\n"
        )

        result = parse_to_dict(conf)
        assert isinstance(result["bind"], list)
        assert len(result["bind"]) == 3
        assert result["bind"][0] == "SUPER, Q, killactive,"
        assert result["bind"][1] == "SUPER, Return, exec, kitty"

    def test_single_keyword_stays_string(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("monitor = DP-2, 1920x1080, 0x0, 1\n")

        result = parse_to_dict(conf)
        assert isinstance(result["monitor"], str)
        assert result["monitor"] == "DP-2, 1920x1080, 0x0, 1"

    def test_repeated_assignment_becomes_list(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("key = first\nkey = second\n")

        result = parse_to_dict(conf)
        assert result["key"] == ["first", "second"]

    def test_source_glob(self, tmp_path):
        conf_dir = tmp_path / "conf.d"
        conf_dir.mkdir()
        (conf_dir / "01.conf").write_text("a = 1\n")
        (conf_dir / "02.conf").write_text("b = 2\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {conf_dir}/*\n")

        result = parse_to_dict(main)
        assert result["a"] == "1"
        assert result["b"] == "2"
