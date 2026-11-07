"""Entry point for the standalone exe built by 'Build Exe.bat' (PyInstaller).

Running from source still works the usual way:  python -m vshelper
"""

import sys

from vshelper.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
