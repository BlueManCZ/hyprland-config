"""Property-based tests for round-trip parsing invariants and fuzz testing."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hyprland_config._model import Variable
from hyprland_config._parser import ParseError, parse_string

# -- Strategies for generating valid Hyprland config fragments --

_IDENT = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]{0,15}", fullmatch=True)
_VALUE = st.from_regex(r"[a-zA-Z0-9_./ -]{0,40}", fullmatch=True).filter(bool)
_INDENT = st.sampled_from(["", "    ", "        "])


def blank_line() -> st.SearchStrategy[str]:
    return st.just("\n")


@st.composite
def comment_line(draw: st.DrawFn) -> str:
    text = draw(st.from_regex(r"[a-zA-Z0-9 _./-]{0,40}", fullmatch=True))
    return f"# {text}\n"


@st.composite
def variable_line(draw: st.DrawFn) -> str:
    name = draw(_IDENT)
    value = draw(_VALUE)
    return f"${name} = {value}\n"


@st.composite
def assignment_line(draw: st.DrawFn) -> str:
    indent = draw(_INDENT)
    key = draw(_IDENT)
    value = draw(_VALUE)
    return f"{indent}{key} = {value}\n"


@st.composite
def section_block(draw: st.DrawFn) -> str:
    name = draw(_IDENT)
    inner_lines = draw(st.lists(assignment_line(), min_size=0, max_size=5))
    inner = "".join(inner_lines)
    return f"{name} {{\n{inner}}}\n"


@st.composite
def hyprland_config(draw: st.DrawFn) -> str:
    """Generate a valid Hyprland config string."""
    parts = draw(
        st.lists(
            st.one_of(
                blank_line(),
                comment_line(),
                variable_line(),
                assignment_line(),
                section_block(),
            ),
            min_size=0,
            max_size=20,
        )
    )
    return "".join(parts)


class TestRoundTripProperty:
    """For any valid config, parse(serialize(parse(text))) == parse(text) structurally."""

    @given(config=hyprland_config())
    @settings(max_examples=50)
    def test_serialize_roundtrip(self, config: str):
        """parse_string(doc.serialize()) produces identical serialization."""
        doc = parse_string(config)
        serialized = doc.serialize()
        doc2 = parse_string(serialized)
        assert doc2.serialize() == serialized

    @given(config=hyprland_config())
    @settings(max_examples=50)
    def test_line_count_preserved(self, config: str):
        """Parsing preserves the number of lines."""
        doc = parse_string(config)
        raw_count = len(config.splitlines(keepends=True)) if config else 0
        assert len(doc.lines) == raw_count

    @given(config=hyprland_config())
    @settings(max_examples=50)
    def test_variables_consistent(self, config: str):
        """Variables dict matches Variable nodes in the document."""
        doc = parse_string(config)
        var_nodes = {line.name: line.value for line in doc.lines if isinstance(line, Variable)}
        assert doc.variables == var_nodes

    @given(config=hyprland_config())
    @settings(max_examples=50)
    def test_to_dict_does_not_crash(self, config: str):
        """to_dict() never crashes on valid generated configs."""
        doc = parse_string(config)
        doc.to_dict()  # should not raise

    @given(config=hyprland_config())
    @settings(max_examples=50)
    def test_lenient_matches_strict_on_valid(self, config: str):
        """Lenient mode produces identical results for valid configs."""
        strict = parse_string(config)
        lenient = parse_string(config, lenient=True)
        assert strict.serialize() == lenient.serialize()
        assert lenient.errors == []


# -- Strategy for arbitrary / malformed input --

_arbitrary_text = st.text(
    alphabet=st.characters(codec="utf-8", categories=("L", "M", "N", "P", "S", "Z", "Cc")),
    min_size=0,
    max_size=500,
)


class TestFuzzArbitraryInput:
    """Feed arbitrary text to the parser to find crash bugs in error paths."""

    @given(text=_arbitrary_text)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_lenient_never_crashes(self, text: str):
        """Lenient mode must never crash, regardless of input."""
        doc = parse_string(text, lenient=True)
        assert doc is not None
        doc.serialize()

    @given(text=_arbitrary_text)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_strict_only_raises_parse_error(self, text: str):
        """Strict mode should only raise ParseError, never other exceptions."""
        try:
            doc = parse_string(text)
            doc.serialize()
        except ParseError:
            pass
