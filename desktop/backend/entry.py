"""PyInstaller entry point for the bundled ReverseAI backend.

Frozen into a single executable (``reverseai-server``) that the desktop app
launches instead of requiring a system Python. It just runs the normal CLI, so
``reverseai-server serve --host 127.0.0.1 --port N --store DIR`` works exactly
like ``python -m reverseai serve``.
"""

import multiprocessing
import sys


def main() -> int:
    from reverseai.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    # Safe when frozen and if any code uses multiprocessing.
    multiprocessing.freeze_support()
    sys.exit(main())
