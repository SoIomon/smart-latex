import sys
from pathlib import Path

# 让 import app.xxx 能正常工作
sys.path.insert(0, str(Path(__file__).parent.parent))
