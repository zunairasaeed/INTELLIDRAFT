"""
Helpers to load JSON assets (e.g., publisher_field_mapping.json).
"""

import json
from pathlib import Path
from typing import Any, Dict


def load_publisher_mapping() -> Dict[str, Any]:
    """
    Load the publisher_field_mapping.json from the database directory.
    """
    project_root = Path(__file__).resolve().parents[3]
    json_path = project_root / "database" / "Journel_recommendations" / "publisher_field_mapping.json"

    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)

