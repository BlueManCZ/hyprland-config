"""Tests for coerce_config_value and value_to_conf."""

from hyprland_config import coerce_config_value, value_to_conf


class TestCoerceConfigValue:
    def test_bool_true(self):
        assert coerce_config_value("true", "bool") is True
        assert coerce_config_value("1", "bool") is True
        assert coerce_config_value("yes", "bool") is True

    def test_bool_false(self):
        assert coerce_config_value("false", "bool") is False
        assert coerce_config_value("0", "bool") is False

    def test_int(self):
        assert coerce_config_value("42", "int") == 42

    def test_float(self):
        assert coerce_config_value("3.14", "float") == 3.14

    def test_string_passthrough(self):
        assert coerce_config_value("hello", "string") == "hello"

    def test_unknown_type_returns_string(self):
        assert coerce_config_value("42", "color") == "42"

    def test_invalid_int_returns_string(self):
        assert coerce_config_value("notanumber", "int") == "notanumber"


class TestValueToConf:
    def test_bool_true(self):
        assert value_to_conf(True) == "1"

    def test_bool_false(self):
        assert value_to_conf(False) == "0"

    def test_int(self):
        assert value_to_conf(42) == "42"

    def test_float(self):
        assert value_to_conf(3.14) == "3.14"

    def test_string(self):
        assert value_to_conf("hello") == "hello"

    def test_gradient_normalizes_bare_hex(self):
        assert value_to_conf("ff1a2b3c ff4d5e6f 45deg") == "0xff1a2b3c 0xff4d5e6f 45deg"

    def test_gradient_preserves_existing_prefix(self):
        assert value_to_conf("0xff1a2b3c 0xff4d5e6f 45deg") == "0xff1a2b3c 0xff4d5e6f 45deg"

    def test_non_gradient_string_unchanged(self):
        assert value_to_conf("ff1a2b3c") == "ff1a2b3c"
