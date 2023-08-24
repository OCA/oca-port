# Copyright 2024 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import hashlib
import json
import os
import pathlib
from collections import defaultdict

from . import misc


class Session:
    """Manage the user's session data, in respect to XDG conventions.

    This class is used to store the list of processed/blacklisted PRs or modules
    during a porting session.
    """

    _cache_dirname = "oca-port"
    _sessions_dirname = "sessions"

    def __init__(self, app, name):
        """Initialize user's session manager."""
        self.app = app
        self.dir_path = self._get_dir_path()
        self._sessions_dir_path = self._get_sessions_dir_path()
        self._key = hashlib.shake_256(name.encode()).hexdigest(3)
        session_file = (
            f"{self.app.addon}"
            f"-{self.app.source_version}-{self.app.target_version}"
            f"-{self._key}.json"
        )
        self._session_path = self._sessions_dir_path.joinpath(session_file)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.clear()

    @classmethod
    def _get_dir_path(cls):
        """Return the path of the session directory."""
        default_cache_dir_path = pathlib.Path.home().joinpath(".cache")
        return pathlib.Path(
            os.environ.get("XDG_CACHE_HOME", default_cache_dir_path),
            cls._cache_dirname,
        )

    def _get_sessions_dir_path(self):
        """Return the dir path storing sessions data."""
        return self.dir_path.joinpath(
            self._sessions_dirname,
            self.app.upstream_org,
        )

    def get_data(self):
        """Return the data of the session."""
        try:
            with self._session_path.open() as file_:
                return json.load(file_, object_hook=misc.defaultdict_from_dict)
        except (json.JSONDecodeError, FileNotFoundError):
            # Mainly to handle empty files (first initialization of the session)
            # but also to not crash if JSON files get corrupted.
            # Returns a "nested dict" object to not worry about checking keys
            nested_dict = lambda: defaultdict(nested_dict)  # noqa
            return nested_dict()

    def set_data(self, data):
        """Store `data` for the given `session`."""
        self._sessions_dir_path.mkdir(parents=True, exist_ok=True)
        self._save_data(data, self._session_path)

    def _save_data(self, data, path):
        try:
            with path.open(mode="w") as file_:
                json.dump(data, file_, indent=2)
        except Exception:
            pass

    def clear(self):
        """Clear the session file."""
        if self._session_path and self._session_path.exists():
            self._session_path.unlink()
