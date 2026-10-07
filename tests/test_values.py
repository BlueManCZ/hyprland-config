"""Tests for coerce_config_value and value_to_conf."""

from hyprland_config import coerce_config_value, value_to_conf
from hyprland_config._core import option_type


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
        assert value_to_conf(True) == "true"

    def test_bool_false(self):
        assert value_to_conf(False) == "false"

    def test_int(self):
        assert value_to_conf(42) == "42"

    def test_float(self):
        assert value_to_conf(3.14) == "3.14"

    def test_string(self):
        assert value_to_conf("hello") == "hello"

    def test_passthrough_does_not_touch_strings(self):
        # value_to_conf is intentionally pass-through for str — gradient
        # normalization or other transforms belong to dedicated typed APIs
        # (see Color/Gradient in _types.py).
        assert value_to_conf("ff1a2b3c ff4d5e6f 45deg") == "ff1a2b3c ff4d5e6f 45deg"
        assert value_to_conf("ff1a2b3c") == "ff1a2b3c"


class TestOptionType:
    def test_string_typed_option(self):
        assert option_type("input:kb_layout") == "string"

    def test_bool_typed_option(self):
        assert option_type("general:resize_on_border") == "bool"

    def test_nested_option(self):
        assert option_type("input:touchpad:tap_button_map") == "string"

    def test_unknown_key_has_no_type(self):
        # A plugin's option, a typo, or a key newer than the installed
        # schema: callers fall back to reading the value's shape.
        assert option_type("general:nosuchoption") is None
        assert option_type("plugin:dynamic-cursors:mode") is None

    def test_device_field_resolves_as_the_input_option(self):
        # A ``device { … }`` block overrides the matching ``input:`` option.
        assert option_type("device:kb_layout") == "string"
        assert option_type("device:natural_scroll") == "bool"
