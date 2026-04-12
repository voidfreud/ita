import sys
from pathlib import Path

# Mirror the sys.path setup in ita.py so bare _* imports resolve
sys.path.insert(0, str(Path(__file__).parent))

from ita import cli  # noqa: E402 — must come after sys.path modification

cli()
