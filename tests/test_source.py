"""Tests for source following, path resolution, and cycle detection."""

from hyprland_config import (
    Assignment,
    Keyword,
    Source,
    load,
    parse_to_dict,
)

# ---------------------------------------------------------------------------
# Document source following
# ---------------------------------------------------------------------------


class TestDocumentSourceFollowing:
    def test_source_nodes_get_documents(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("sub_key = sub_value\n")
        main = tmp_path / "main.conf"
        main.write_text(f"main_key = 1\nsource = {sub}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[1]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1
        assert source_node.documents[0].path == sub.resolve()

    def test_sourced_document_is_independently_serializable(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("key = value\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        sub_doc = source_node.documents[0]
        assert sub_doc.serialize() == "key = value\n"

    def test_variables_merge_from_sources(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("$myVar = hello\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = load(main, follow_sources=True)
        assert doc.variables["myVar"] == "hello"

    def test_glob_source_multiple_documents(self, tmp_path):
        conf_dir = tmp_path / "conf.d"
        conf_dir.mkdir()
        (conf_dir / "01.conf").write_text("a = 1\n")
        (conf_dir / "02.conf").write_text("b = 2\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {conf_dir}/*\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 2

    def test_follow_sources_by_default(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("key = value\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = load(main)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1

    def test_no_follow_sources_when_disabled(self, tmp_path):
        sub = tmp_path / "sub.conf"
        sub.write_text("key = value\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = load(main, follow_sources=False)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 0

    def test_nested_source_following(self, tmp_path):
        c = tmp_path / "c.conf"
        c.write_text("deep = yes\n")
        b = tmp_path / "b.conf"
        b.write_text(f"source = {c}\n")
        a = tmp_path / "a.conf"
        a.write_text(f"source = {b}\n")

        doc = load(a, follow_sources=True)
        a_source = doc.lines[0]
        assert isinstance(a_source, Source)
        b_doc = a_source.documents[0]
        b_source = b_doc.lines[0]
        assert isinstance(b_source, Source)
        c_doc = b_source.documents[0]
        node = c_doc.find("deep")
        assert node is not None and node.value == "yes"


# ---------------------------------------------------------------------------
# Absolute path globs
# ---------------------------------------------------------------------------


class TestAbsolutePathGlobs:
    """Verify that absolute paths with glob patterns resolve correctly."""

    def test_absolute_glob(self, tmp_path):
        """source = /absolute/path/*.conf works."""
        conf_dir = tmp_path / "hypr"
        conf_dir.mkdir()
        (conf_dir / "a.conf").write_text("a = 1\n")
        (conf_dir / "b.conf").write_text("b = 2\n")

        main = tmp_path / "main.conf"
        main.write_text(f"source = {conf_dir}/*.conf\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 2
        all_keys = []
        for d in source_node.documents:
            for ln in d.lines:
                if isinstance(ln, Source):
                    continue
                if isinstance(ln, (Assignment, Keyword)):
                    all_keys.append(ln.key)
        assert "a" in all_keys
        assert "b" in all_keys

    def test_absolute_glob_no_matches(self, tmp_path):
        """Glob with no matches results in empty documents list."""
        main = tmp_path / "main.conf"
        main.write_text(f"source = {tmp_path}/nonexistent/*.conf\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 0

    def test_absolute_path_no_glob(self, tmp_path):
        """Plain absolute path (no glob) resolves correctly."""
        sub = tmp_path / "sub.conf"
        sub.write_text("key = value\n")

        main = tmp_path / "main.conf"
        main.write_text(f"source = {sub}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1
        node = source_node.documents[0].find("key")
        assert node is not None and node.value == "value"

    def test_nix_store_style_path(self, tmp_path):
        """Paths resembling /nix/store/hash-name/... resolve correctly."""
        nix_dir = tmp_path / "nix" / "store" / "abc123-hyprland" / "etc"
        nix_dir.mkdir(parents=True)
        conf = nix_dir / "hyprland.conf"
        conf.write_text("nix_key = nix_value\n")

        main = tmp_path / "main.conf"
        main.write_text(f"source = {conf}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1
        node = source_node.documents[0].find("nix_key")
        assert node is not None and node.value == "nix_value"

    def test_nix_store_glob(self, tmp_path):
        """Glob inside a nix-store-like path resolves correctly."""
        nix_dir = tmp_path / "nix" / "store" / "abc123-hyprland" / "conf.d"
        nix_dir.mkdir(parents=True)
        (nix_dir / "01.conf").write_text("x = 1\n")
        (nix_dir / "02.conf").write_text("y = 2\n")

        main = tmp_path / "main.conf"
        main.write_text(f"source = {nix_dir}/*.conf\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 2

    def test_recursive_glob(self, tmp_path):
        """source = /path/**/*.conf with recursive glob."""
        d = tmp_path / "conf"
        d.mkdir()
        sub = d / "sub"
        sub.mkdir()
        (d / "top.conf").write_text("a = 1\n")
        (sub / "nested.conf").write_text("b = 2\n")

        main = tmp_path / "main.conf"
        main.write_text(f"source = {d}/**/*.conf\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 2


class TestSymlinks:
    """Symlink chains should be followed without breaking cycle detection."""

    def test_symlink_to_file(self, tmp_path):
        """Sourcing a symlink to a real file works."""
        real = tmp_path / "real.conf"
        real.write_text("sym_key = sym_value\n")
        link = tmp_path / "link.conf"
        link.symlink_to(real)

        main = tmp_path / "main.conf"
        main.write_text(f"source = {link}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1
        node = source_node.documents[0].find("sym_key")
        assert node is not None and node.value == "sym_value"

    def test_symlink_to_directory_with_glob(self, tmp_path):
        """Glob through a symlinked directory works."""
        real_dir = tmp_path / "real_conf"
        real_dir.mkdir()
        (real_dir / "a.conf").write_text("a = 1\n")
        link_dir = tmp_path / "link_conf"
        link_dir.symlink_to(real_dir)

        main = tmp_path / "main.conf"
        main.write_text(f"source = {link_dir}/*.conf\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1

    def test_symlink_chain(self, tmp_path):
        """A chain of symlinks resolves correctly."""
        real = tmp_path / "real.conf"
        real.write_text("chain = yes\n")
        link1 = tmp_path / "link1.conf"
        link1.symlink_to(real)
        link2 = tmp_path / "link2.conf"
        link2.symlink_to(link1)

        main = tmp_path / "main.conf"
        main.write_text(f"source = {link2}\n")

        doc = load(main, follow_sources=True)
        source_node = doc.lines[0]
        assert isinstance(source_node, Source)
        assert len(source_node.documents) == 1
        node = source_node.documents[0].find("chain")
        assert node is not None and node.value == "yes"

    def test_symlink_cycle_detected(self, tmp_path):
        """Two symlinks pointing at the same real file don't cause double-parse."""
        real = tmp_path / "real.conf"
        link1 = tmp_path / "link1.conf"
        link2 = tmp_path / "link2.conf"

        # real sources link1, link1 symlinks to link2, link2 symlinks to real
        # This creates a cycle via resolved paths
        real.write_text(f"key = value\nsource = {link1}\n")
        link1.symlink_to(link2)
        link2.symlink_to(real)

        doc = load(real, follow_sources=True)
        # Should complete without infinite loop — cycle is detected via resolved paths
        node = doc.find("key")
        assert node is not None and node.value == "value"


# ---------------------------------------------------------------------------
# Source cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_cycle_skipped_silently(self, tmp_path):
        """Cycles are silently skipped (like Hyprland itself does)."""
        a = tmp_path / "a.conf"
        b = tmp_path / "b.conf"
        a.write_text(f"key_a = 1\nsource = {b}\n")
        b.write_text(f"key_b = 2\nsource = {a}\n")

        result = parse_to_dict(a)
        assert result["key_a"] == "1"
        assert result["key_b"] == "2"

    def test_direct_self_reference(self, tmp_path):
        """A file sourcing itself is detected and skipped."""
        a = tmp_path / "a.conf"
        a.write_text(f"key = value\nsource = {a}\n")

        result = parse_to_dict(a)
        assert result["key"] == "value"
