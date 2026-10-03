"""Show Python loop progress in a local browser page."""

from .web import Qtqdm
from .session import TrainingSession

tqdm = Qtqdm

__all__ = ["Qtqdm", "tqdm", "TrainingSession"]
