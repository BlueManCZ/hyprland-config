"""Tests for atomic file writing."""

from hyprland_config import atomic_write, load


class TestAtomicWrite:
    def test_write_creates_file(self, tmp_path):
        path = tmp_path / "out.conf"
        atomic_write(path, "key = value\n")
        assert path.read_text() == "key = value\n"

    def test_write_overwrites_existing(self, tmp_path):
        path = tmp_path / "out.conf"
        path.write_text("old content\n")
        atomic_write(path, "new content\n")
        assert path.read_text() == "new content\n"

    def test_write_creates_parent_directories(self, tmp_path):
        path = tmp_path / "a" / "b" / "out.conf"
        atomic_write(path, "nested = yes\n")
        assert path.read_text() == "nested = yes\n"

    def test_write_empty_content(self, tmp_path):
        path = tmp_path / "empty.conf"
        atomic_write(path, "")
        assert path.read_text() == ""

    def test_no_temp_file_left_on_success(self, tmp_path):
        path = tmp_path / "out.conf"
        atomic_write(path, "content\n")
        tmp_files = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
        assert tmp_files == []


class TestDocumentSave:
    def test_dirty_files_clears_after_save(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("key = value\n")

        doc = load(conf, follow_sources=False)
        doc.set("key", "new")
        assert len(doc.dirty_files()) == 1
        doc.save()
        assert doc.dirty_files() == []

    def test_save_recursive_only_writes_dirty(self, tmp_path):
        clean = tmp_path / "clean.conf"
        dirty_f = tmp_path / "dirty.conf"
        clean.write_text("a = 1\n")
        dirty_f.write_text("b = 2\n")
        main = tmp_path / "main.conf"
        main.write_text(f"source = {clean}\nsource = {dirty_f}\n")

        doc = load(main, follow_sources=True)

        # Modify only the second sourced file (recursive by default)
        doc.set("b", "99")

        # Record file modification times before save
        clean_mtime = clean.stat().st_mtime
        doc.save()

        # clean.conf should NOT have been rewritten
        assert clean.stat().st_mtime == clean_mtime
        # dirty.conf should have the new value
        assert "b = 99" in dirty_f.read_text()

    def test_save_writes_correct_content(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text("general {\n    gaps_in = 5\n}\n")

        doc = load(conf, follow_sources=False)
        doc.set("general:gaps_in", "20")
        doc.save()

        assert conf.read_text() == "general {\n    gaps_in = 20\n}\n"
