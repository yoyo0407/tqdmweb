import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

from qtqdm import patch
from qtqdm.board_files import validate_launch
from qtqdm.board_process import launch_command
from qtqdm.patch import PatchedTqdm

SCRIPT = '''
from tqdm import tqdm, trange
from tqdm.auto import tqdm as auto_tqdm
import sys

for item in trange(3, desc="t", unknown_option=1):
    pass
bar = tqdm(range(3), "desc", 3, unit_scale=True, weird=True)
for step in bar:
    bar.set_postfix(loss=1.0 / (step + 1))
    bar.set_postfix_str("x")
    bar.refresh()
tqdm.write("hi")
for item in auto_tqdm(range(2)):
    pass
print("TYPES", type(bar).__name__, type(auto_tqdm).__name__, bar.description, bar.total, bar.metrics["postfix"])
'''


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.modules = {name: sys.modules.get(name) for name in ("tqdm", "tqdm.auto", "tqdm.autonotebook")}
        self.environment = os.environ.get("TQDMBOARD")
        os.environ["TQDMBOARD"] = "1"
        patch._warned.clear()
        self.attributes = []
        for name in self.modules:
            try:
                module = __import__(name, fromlist=["x"])
            except ImportError:
                continue
            self.attributes.append((module, getattr(module, "tqdm", None), getattr(module, "trange", None)))

    def tearDown(self):
        patch.finish()
        for module, tqdm_class, trange_function in self.attributes:
            if tqdm_class is not None:
                module.tqdm = tqdm_class
            if trange_function is not None:
                module.trange = trange_function
        for name, module in self.modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if self.environment is None:
            os.environ.pop("TQDMBOARD", None)
        else:
            os.environ["TQDMBOARD"] = self.environment

    def run_script(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "train.py")
            path.write_text(SCRIPT)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                runpy.run_path(str(path), run_name="__main__")
        return out.getvalue(), err.getvalue()

    def check_script(self):
        out, err = self.run_script()
        self.assertIn("hi", out)
        self.assertIn("TYPES PatchedTqdm", out)
        self.assertIn("desc 3 x", out)
        self.assertEqual(err.count("ignored tqdm arguments"), 2)  # unknown_option, then weird
        self.assertNotIn("unit_scale", err)  # accepted display option

    def test_patches_installed_tqdm(self):
        try:
            import tqdm  # noqa: F401
        except ImportError:
            self.skipTest("real tqdm not installed")
        description = patch.install()
        self.assertIn("tqdm.tqdm", description)
        self.assertIn("tqdm.auto.tqdm", description)
        self.check_script()

    def test_stand_in_when_tqdm_missing(self):
        for name in self.modules:
            sys.modules[name] = None
        self.assertEqual(patch.install(), "stand-in tqdm, tqdm.auto")
        self.check_script()

    def test_unknown_kwargs_warn_once(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(2):
                PatchedTqdm(range(2), gui=True, open_browser=False, capture_console=False)
        self.assertEqual(err.getvalue().count("gui"), 1)

    def test_positional_desc_and_total(self):
        bar = PatchedTqdm(None, "label", 7, open_browser=False, capture_console=False)
        self.assertEqual((bar.description, bar.total), ("label", 7))
        bar = PatchedTqdm(range(4), open_browser=False, capture_console=False, desc=None)
        self.assertEqual((bar.description, bar.total), ("", 4))

    def test_postfix_str_and_noops(self):
        bar = PatchedTqdm(total=2, open_browser=False, capture_console=False)
        bar.set_postfix_str("abc")
        bar.refresh(); bar.clear(); bar.display(); bar.unpause()
        self.assertEqual(bar.metrics["postfix"], "abc")

    def test_finish_closes_outer_pages(self):
        outer = PatchedTqdm(range(2), open_browser=False, capture_console=False)
        for _ in outer:
            inner = PatchedTqdm(range(2))
            list(inner)
        self.assertIsNotNone(outer.server)
        self.assertEqual(patch._roots, [outer])  # nested bars are not roots
        patch.finish()
        self.assertIsNone(outer.server)
        self.assertEqual((outer.state, patch._roots), ("finished", []))

    def test_finish_marks_script_error(self):
        bar = PatchedTqdm(range(5), open_browser=False, capture_console=False)
        with self.assertRaises(RuntimeError):
            for item in bar:
                if item == 2:
                    raise RuntimeError("boom")
        patch.finish(RuntimeError("boom"))
        self.assertEqual((bar.state, bar.error), ("failed", "RuntimeError: boom"))

    def test_main_usage_errors(self):
        from qtqdm.__main__ import main
        old = sys.argv
        try:
            for argv in (["qtqdm"], ["qtqdm", "missing_script.py"]):
                sys.argv = argv
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(), 2)
        finally:
            sys.argv = old


class LaunchTests(unittest.TestCase):
    def config(self, **extra):
        # A real file stands in for python: validation only checks that it exists.
        folder = Path(__file__).resolve().parent
        return {"script": str(Path(__file__).resolve()), "python": str(Path(__file__).resolve()),
                "working_directory": str(folder), "arguments": "--a 1", **extra}

    def test_validate_patch_flag(self):
        self.assertIs(validate_launch(self.config())["patch_tqdm"], False)
        self.assertIs(validate_launch(self.config(patch_tqdm=True))["patch_tqdm"], True)
        with self.assertRaises(ValueError):
            validate_launch(self.config(patch_tqdm="yes"))

    def test_command(self):
        plain = launch_command(validate_launch(self.config()))
        patched = launch_command(validate_launch(self.config(patch_tqdm=True)))
        self.assertNotIn("-m", plain)
        self.assertEqual(patched[1:5], ["-u", "-m", "qtqdm", str(Path(__file__).resolve())])
        self.assertEqual(patched[-2:], ["--a", "1"])


if __name__ == "__main__":
    unittest.main()
