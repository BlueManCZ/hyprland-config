"""Format-agnostic core: the Document AST plus shared utilities.

The :class:`Document` tree is the canonical in-memory representation of a
Hyprland configuration. The :mod:`hyprland_config._hyprlang` and
:mod:`hyprland_config._lua` packages each translate their respective
on-disk format to and from this AST.
"""

from hyprland_config._core._animation import (
    ANIM_CHILDREN,
    ANIM_FLAT,
    ANIM_LOOKUP,
    ANIMATION_TREE,
    HYPRLAND_NATIVE_CURVES,
    AnimationData,
    BezierData,
    get_styles_for,
)
from hyprland_config._core._bind import BIND_FLAG_MAP, BindData
from hyprland_config._core._expr import (
    ExprError,
    evaluate_expression,
    expand_expressions,
    expand_value,
)
from hyprland_config._core._model import (
    Assignment,
    BlankLine,
    Comment,
    Conditional,
    Document,
    ErrorLine,
    KeyValueLine,
    Keyword,
    Line,
    Rule,
    SectionClose,
    SectionOpen,
    Source,
    Variable,
)
from hyprland_config._core._rule_split import split_top_level
from hyprland_config._core._rules import (
    LAYER_BOOL_EFFECTS,
    LAYERRULE_V3_VERSION,
    V3_BOOL_EFFECTS,
    V3_BOOL_MATCHERS,
    WINDOWRULE_V3_VERSION,
)
from hyprland_config._core._types import (
    Color,
    Gradient,
    Vec2,
    normalize_gradient_string,
    parse_version,
)
from hyprland_config._core._values import (
    coerce_config_value,
    option_type,
    parse_hyprlang_bool,
    value_to_conf,
)
from hyprland_config._core._writer import atomic_write

__all__ = [
    "ANIM_CHILDREN",
    "ANIM_FLAT",
    "ANIM_LOOKUP",
    "ANIMATION_TREE",
    "BIND_FLAG_MAP",
    "Assignment",
    "AnimationData",
    "BezierData",
    "BindData",
    "BlankLine",
    "Color",
    "Comment",
    "Conditional",
    "Document",
    "ErrorLine",
    "ExprError",
    "Gradient",
    "HYPRLAND_NATIVE_CURVES",
    "KeyValueLine",
    "Keyword",
    "LAYER_BOOL_EFFECTS",
    "LAYERRULE_V3_VERSION",
    "Line",
    "Rule",
    "SectionClose",
    "SectionOpen",
    "Source",
    "V3_BOOL_EFFECTS",
    "V3_BOOL_MATCHERS",
    "Variable",
    "Vec2",
    "WINDOWRULE_V3_VERSION",
    "atomic_write",
    "coerce_config_value",
    "evaluate_expression",
    "expand_expressions",
    "expand_value",
    "get_styles_for",
    "normalize_gradient_string",
    "option_type",
    "parse_hyprlang_bool",
    "parse_version",
    "split_top_level",
    "value_to_conf",
]
