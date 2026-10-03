"""Make `from tqdm import tqdm` use Qtqdm, so existing scripts need no edits."""

import importlib
import inspect
import sys
import types

from .web import Qtqdm, TQDM_DISPLAY_OPTIONS

# Keyword names Qtqdm understands; anything else is dropped with a warning.
_ACCEPTED = (set(inspect.signature(Qtqdm.__init__).parameters) - {"self", "items", "total", "description"}) | TQDM_DISPLAY_OPTIONS
_warned = set()
_roots = []  # outermost bars, closed by finish() after the script returns


class PatchedTqdm(Qtqdm):
    """Qtqdm that tolerates tqdm arguments and methods it does not implement."""

    def __init__(self, iterable=None, desc=None, total=None, *args, **kwargs):
        # tqdm's positional order is (iterable, desc, total, leave, ...); Qtqdm's differs.
        if args:
            kwargs.setdefault("leave", args[0])
        ignored = sorted(name for name in kwargs if name not in _ACCEPTED)
        if len(args) > 1:
            ignored.append("extra positional arguments")
        new = [name for name in ignored if name not in _warned]
        if new:
            _warned.update(new)
            print("qtqdm: ignored tqdm arguments: " + ", ".join(new), file=sys.stderr)
        kwargs = {name: value for name, value in kwargs.items() if name in _ACCEPTED}
        super().__init__(iterable, total=total, desc=desc, **kwargs)
        if not self.is_child and not self.disable:
            _roots.append(self)

    # Terminal-only methods: nothing to redraw on a web page.
    def refresh(self, *args, **kwargs):
        pass

    def clear(self, *args, **kwargs):
        pass

    def display(self, *args, **kwargs):
        pass

    def unpause(self):
        pass

    def set_postfix_str(self, s="", refresh=True):
        self.set_postfix(postfix=s)

    @classmethod
    def write(cls, s, file=None, end="\n"):
        print(s, file=file, end=end)

    # reset() is left out on purpose: a Qtqdm bar monitors exactly one run.


def trange(*args, **kwargs):
    return PatchedTqdm(range(*args), **kwargs)


def _replace(module_name):
    """Swap tqdm/trange on one real tqdm module; returns the names replaced."""
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return []
    names = []
    for attribute, value in (("tqdm", PatchedTqdm), ("trange", trange)):
        if hasattr(module, attribute):
            setattr(module, attribute, value)
            names.append(f"{module_name}.{attribute}")
    return names


def _stand_in(name):
    module = types.ModuleType(name)
    module.tqdm = PatchedTqdm
    module.trange = trange
    return module


def finish(error=None):
    """Plain tqdm scripts never call close(); end every page and save its record here."""
    if error is not None:
        for bar in _roots:
            if bar.state in ("waiting", "running", "stopped"):
                bar.state = "failed"
                bar.error = f"{type(error).__name__}: {error}"
    if _roots and error is None:
        _roots[-1].wait()  # standalone: keep the last page until Enter; Board: close at once
    for bar in _roots:
        bar.close()
    _roots.clear()


def install():
    """Call before the script imports tqdm. Returns a short description of what changed."""
    try:
        import tqdm  # noqa: F401
    except ImportError:
        package = _stand_in("tqdm")
        package.__path__ = []  # lets `import tqdm.auto` treat it as a package
        package.auto = _stand_in("tqdm.auto")
        sys.modules["tqdm"] = package
        sys.modules["tqdm.auto"] = package.auto
        return "stand-in tqdm, tqdm.auto"
    names = []
    for module_name in ("tqdm", "tqdm.auto", "tqdm.autonotebook"):
        names += _replace(module_name)
    return ", ".join(names)
