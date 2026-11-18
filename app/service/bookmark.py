import os
import json
import shutil
from typing import List, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP_DIR = os.path.expanduser("~/.myxl_backup")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

BOOKMARK_FILE = os.path.join(BASE_DIR, "bookmark.json")
BACKUP_BOOKMARK_FILE = os.path.join(BACKUP_DIR, "bookmark.json")


class Bookmark:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.packages: List[Dict] = []
            self.filepath = BOOKMARK_FILE
            os.makedirs(BASE_DIR, exist_ok=True)
            os.makedirs(BACKUP_DIR, exist_ok=True)

            if not os.path.exists(self.filepath) and os.path.exists(BACKUP_BOOKMARK_FILE):
                try:
                    shutil.copy2(BACKUP_BOOKMARK_FILE, self.filepath)
                except Exception:
                    pass

            if os.path.exists(self.filepath):
                self.load_bookmark()
            else:
                self._save([])

            self._initialized = True

    def _save(self, data: List[Dict]):
        """Helper to write JSON safely + auto backup."""
        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        for p in (self.filepath, BACKUP_BOOKMARK_FILE):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def _ensure_schema(self):
        """Ensure all bookmarks have the latest schema fields."""
        updated = False
        for p in self.packages:
            if "family_name" not in p:
                p["family_name"] = ""
                updated = True
            if "order" not in p:
                p["order"] = 0
                updated = True
            if "option_code" not in p:
                p["option_code"] = ""
                updated = True
        if updated:
            self.save_bookmark()

    def load_bookmark(self):
        """Load bookmarks from JSON file and ensure schema consistency."""
        with open(self.filepath, "r", encoding="utf-8") as f:
            self.packages = json.load(f)
        self._ensure_schema()

    def save_bookmark(self):
        """Save current bookmarks to JSON file."""
        self._save(self.packages)

    def add_bookmark(
        self,
        family_code: str,
        family_name: str,
        is_enterprise: bool,
        variant_name: str,
        option_name: str,
        order: int,
        option_code: str = "",
        reorder_if_exists: bool = False,
    ) -> bool:
        """Add a bookmark at the end of the list (preserving selection order)."""
        existing_idx = None
        for i, p in enumerate(self.packages):
            if option_code and p.get("option_code") and p.get("option_code") == option_code:
                existing_idx = i
                break
            if (
                p.get("family_code") == family_code
                and p.get("variant_name") == variant_name
                and p.get("option_name") == option_name
                and p.get("order") == order
            ):
                existing_idx = i
                break

        if existing_idx is not None:
            if reorder_if_exists:
                del self.packages[existing_idx]
            else:
                print("Bookmark already exists.")
                return False

        self.packages.append(
            {
                "family_name": family_name,
                "family_code": family_code,
                "is_enterprise": is_enterprise,
                "variant_name": variant_name,
                "option_name": option_name,
                "order": order,
                "option_code": option_code,
            }
        )
        self.save_bookmark()
        print("Bookmark added.")
        return True

    def remove_bookmark_by_index(self, index: int) -> bool:
        """Remove a bookmark by its 0-based index."""
        if 0 <= index < len(self.packages):
            del self.packages[index]
            self.save_bookmark()
            print("Bookmark removed by index.")
            return True
        return False

    def remove_bookmark(
        self,
        family_code: str,
        is_enterprise: bool,
        variant_name: str,
        order: int,
        option_name: str | None = None,
    ) -> bool:
        """Remove a bookmark if it exists. Returns True if removed."""
        for i, p in enumerate(self.packages):
            if (
                p["family_code"] == family_code
                and p["is_enterprise"] == is_enterprise
                and p["variant_name"] == variant_name
                and p["order"] == order
                and (option_name is None or p.get("option_name") == option_name)
            ):
                del self.packages[i]
                self.save_bookmark()
                print("Bookmark removed.")
                return True
        print("Bookmark not found.")
        return False

    def clear_bookmarks(self):
        """Remove all bookmarks."""
        self.packages = []
        self.save_bookmark()

    def get_bookmarks(self) -> List[Dict]:
        """Return all bookmarks."""
        return self.packages.copy()


BookmarkInstance = Bookmark()
