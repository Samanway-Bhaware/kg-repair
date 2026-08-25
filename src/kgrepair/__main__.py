"""Support `python -m kgrepair`, equivalent to the `kgrepair` console script."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
