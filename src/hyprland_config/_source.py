"""Source path resolution, glob expansion, and cycle detection."""

import glob
from pathlib import Path


class SourceCycleError(Exception):
    """Raised when a circular source chain is detected."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Circular source detected: {path}")


def resolve_source_paths(
    path_str: str,
    relative_to: Path | None = None,
) -> list[Path]:
    """Resolve a source path string to a list of concrete file paths.

    Handles ~ expansion and glob patterns. Returns sorted results.
    """
    expanded = Path(path_str.strip()).expanduser()

    if not expanded.is_absolute() and relative_to is not None:
        expanded = relative_to / expanded

    expanded_str = str(expanded)
    matches = sorted(glob.glob(expanded_str, recursive=True))
    if not matches:
        # glob.glob misses literal paths containing metacharacters like [ or ].
        # Retry with escaped pattern to handle those as literal filenames.
        matches = sorted(glob.glob(glob.escape(expanded_str), recursive=True))

    paths = [Path(m) for m in matches]
    return [p for p in paths if p.is_file()]
