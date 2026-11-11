"""exit-arc: move your Arc browser sidebar (spaces, pinned tabs, folders,
favourites, extensions list) to Firefox, Zen or Chrome, or export it to plain
files. Python 3.8+ standard library only."""

__version__ = "0.4.1"


class ToolError(Exception):
    """A problem we can explain to the user (printed without a traceback)."""
