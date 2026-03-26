import sys
from pathlib import Path

# Make app/ importable without installing a package
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
