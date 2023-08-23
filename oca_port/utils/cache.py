# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import json
import logging
import os
import pathlib
import shutil
from collections import defaultdict

from . import misc

_logger = logging.getLogger(__name__)


class UserCacheFactory:
    """User's cache manager factory."""

    def __init__(self, app):
        self.app = app

    def build(self):
        """Build the cache manager."""
        if self.app.no_cache:
            return NoCache()
        try:
            cache = UserCache(self.app)
        except Exception:
            # If the cache can't be used (whatever the reason) we fallback on a
            # fake-cache manager.
            _logger.warning(
                "No cache will be used: "
                "unable to initialize the cache folder in %s.",
                UserCache._get_dir_path(),
            )
            cache = NoCache()
        return cache


class NoCache:
    """Fake cache manager class.

    Used if the cache can't be used, e.g. no write access to cache folder.
    """

    def __init__(self, *args, **kwargs):
        """Initialize a fake user's cache manager."""

    def mark_commit_as_ported(self, commit_sha):
        # Do nothing
        pass

    def is_commit_ported(self, commit_sha):
        # A commit is always considered as not ported
        return False

    def store_commit_pr(self, commit_sha: str, data):
        # Do nothing
        pass

    def get_pr_from_commit(self, commit_sha: str):
        # No PR data to return
        return {}

    def clear(self):
        # Do nothing
        pass


class UserCache:
    """Manage the user's cache, in respect to XDG conventions.

    This class manages the following data:
        - a list of already ported commits from one branch to another.

    It allows to speed up further commit scans on a given module.
    """

    _cache_dirname = "oca-port"
    _ported_dirname = "ported"
    _to_port_dirname = "to_port"

    def __init__(self, app):
        """Initialize user's cache manager."""
        self.app = app
        self.dir_path = self._get_dir_path()
        self._ported_commits_path = self._get_ported_commits_path()
        self._ported_commits = self._get_ported_commits()
        self._commits_to_port_path = self._get_commits_to_port_path()
        self._commits_to_port = self._get_commits_to_port()

    @classmethod
    def _get_dir_path(cls):
        """Return the path of the cache directory."""
        default_cache_dir_path = pathlib.Path.home().joinpath(".cache")
        return pathlib.Path(
            os.environ.get("XDG_CACHE_HOME", default_cache_dir_path), cls._cache_dirname
        )

    def _get_ported_commits_path(self):
        """Return the file path storing ported commit."""
        file_name = (
            f"{self.app.addon}_{self.app.from_branch.name}_"
            f"to_{self.app.to_branch.name}.list"
        )
        return self.dir_path.joinpath(
            self._ported_dirname,
            self.app.from_org,
            self.app.repo_name,
            file_name,
        )

    def _get_commits_to_port_path(self):
        """Return the file path storing cached data of commits to port."""
        file_name = (
            f"{self.app.addon}_{self.app.from_branch.name}_"
            f"to_{self.app.to_branch.name}.json"
        )
        return self.dir_path.joinpath(
            self._to_port_dirname,
            self.app.from_org,
            self.app.repo_name,
            file_name,
        )

    def _get_ported_commits(self):
        self._ported_commits_path.parent.mkdir(parents=True, exist_ok=True)
        self._ported_commits_path.touch(exist_ok=True)
        return self._ported_commits_path.read_text().splitlines()

    def _get_commits_to_port(self):
        self._commits_to_port_path.parent.mkdir(parents=True, exist_ok=True)
        self._commits_to_port_path.touch(exist_ok=True)
        try:
            with self._commits_to_port_path.open() as file_:
                return json.load(file_, object_hook=misc.defaultdict_from_dict)
        except json.JSONDecodeError:
            # Mainly to handle empty files (first initialization of the cache)
            # but also to not crash if JSON files get corrupted.
            # Returns a "nested dict" object to not worry about checking keys
            nested_dict = lambda: defaultdict(nested_dict)  # noqa
            return nested_dict()

    def mark_commit_as_ported(self, commit_sha: str):
        """Mark commit as ported."""
        if self.is_commit_ported(commit_sha):
            return
        self._ported_commits.append(commit_sha)
        with self._ported_commits_path.open(mode="a") as file_:
            file_.write(f"{commit_sha}\n")

    def is_commit_ported(self, commit_sha: str):
        """Return `True` if commit is already ported."""
        return commit_sha in self._ported_commits

    def store_commit_pr(self, commit_sha: str, data):
        """Store the original PR data of a commit."""
        pr_number = data["number"]
        self._commits_to_port["pull_requests"][str(pr_number)] = data
        self._commits_to_port["commits"][commit_sha]["pr"] = pr_number
        try:
            with self._commits_to_port_path.open(mode="w") as file_:
                json.dump(self._commits_to_port, file_, indent=2)
        except Exception:
            pass

    def get_pr_from_commit(self, commit_sha: str):
        """Return the original PR data of a commit."""
        pr_number = self._commits_to_port["commits"][commit_sha]["pr"]
        if pr_number:
            return self._commits_to_port["pull_requests"][str(pr_number)]
        return {}

    def clear(self):
        """Clear the cache by removing the content of the cache directory."""
        if self._cache_dirname and str(self.dir_path).endswith(self._cache_dirname):
            shutil.rmtree(self.dir_path)
