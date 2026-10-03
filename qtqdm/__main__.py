"""python -m qtqdm SCRIPT [ARGS...]: run a script with tqdm replaced by Qtqdm."""

import os
import runpy
import sys

from . import patch


def main():
    if len(sys.argv) < 2:
        print("usage: python -m qtqdm SCRIPT [ARGS...]", file=sys.stderr)
        return 2
    script = sys.argv[1]
    if not os.path.isfile(script):
        print(f"qtqdm: script not found: {script}", file=sys.stderr)
        return 2
    patched = patch.install()
    print(f"qtqdm: patched tqdm ({patched}) for {script}", flush=True)
    sys.argv = [script, *sys.argv[2:]]
    sys.path[0] = os.path.dirname(os.path.abspath(script))
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as error:
        patch.finish(None if error.code in (0, None) else error)  # sys.exit(0) is a normal end
        raise
    except BaseException as error:
        patch.finish(error)
        raise
    patch.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
