"""Show Python loop progress in a local browser page."""

from .web import Qtqdm, trange

tqdm = Qtqdm

__all__ = ["Qtqdm", "tqdm", "trange"]
