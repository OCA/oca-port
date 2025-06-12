# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import json
import logging
import os
import pathlib
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

    def get_commit_files(self, commit_sha: str):
        # No commit files to return
        return set()

    def set_commit_files(self, commit_sha: str, files: list):
        # Do nothing
        pass

    def save(self):
        # Do nothing
        pass

    def clear(self):
        # Do nothing
        pass


class UserCache:
    """Manage the user's cache, in respect to XDG conventions.

    This class manages the following data:
        - a list of already ported commits from one branch to another
        - some commits data like impacted file paths

    It allows to speed up further commit scans on a given module.
    """

    _cache_dirname = "oca-port"
    _ported_dirname = "ported"
    _to_port_dirname = "to_port"
    _commits_data_dirname = "commits_data"

    def __init__(self, app):
        """Initialize user's cache manager."""
        self.app = app
        # NOTE: set cache as readonly if the source branch is not linked to
        # an organization (local branch): we cannot put in cache commits data
        # coming from such branch in the behalf of upstream organization/repo,
        # that could produce wrong cache results for further use.
        self.readonly = not self.app.source.org
        self.dir_path = self._get_dir_path()
        self._ported_commits_path = self._get_ported_commits_path()
        self._ported_commits = self._get_ported_commits()
        self._commits_to_port_path = self._get_commits_to_port_path()
        self._commits_to_port = self._get_commits_to_port()
        self._commits_data_path = self._get_commits_data_path()
        self._commits_data = self._get_commits_data()

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
            f"{self.app.addon}_{self.app.source.repo}_{self.app.from_branch.name}_"
            f"to_{self.app.target.repo}_{self.app.to_branch.name}.list"
        )
        return self.dir_path.joinpath(
            self._ported_dirname,
            self.app.upstream_org,
            file_name,
        )

    def _get_commits_to_port_path(self):
        """Return the file path storing cached data of commits to port."""
        file_name = (
            f"{self.app.addon}_{self.app.source.repo}_{self.app.from_branch.name}_"
            f"to_{self.app.target.repo}_{self.app.to_branch.name}.json"
        )
        return self.dir_path.joinpath(
            self._to_port_dirname,
            self.app.upstream_org,
            file_name,
        )

    def _get_commits_data_path(self):
        """Return the file path storing commits cached data."""
        file_name = f"{self.app.repo_name}.json"
        if self.app.source.repo != self.app.target.repo:
            file_name = f"{self.app.source.repo}_{self.app.target.repo}.json"
        return self.dir_path.joinpath(
            self._commits_data_dirname,
            self.app.upstream_org,
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

    def _get_commits_data(self):
        self._commits_data_path.parent.mkdir(parents=True, exist_ok=True)
        self._commits_data_path.touch(exist_ok=True)
        try:
            with self._commits_data_path.open() as file_:
                return json.load(file_, object_hook=misc.defaultdict_from_dict)
        except json.JSONDecodeError:
            # Mainly to handle empty files (first initialization of the cache)
            # but also to not crash if JSON files get corrupted.
            # Returns a "nested dict" object to not worry about checking keys
            nested_dict = lambda: defaultdict(nested_dict)  # noqa
            return nested_dict()

    def mark_commit_as_ported(self, commit_sha: str):
        """Mark commit as ported."""
        if self.readonly:
            return
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
        if self.readonly:
            return
        pr_number = data["number"]
        self._commits_to_port["pull_requests"][str(pr_number)] = data
        self._commits_to_port["commits"][commit_sha]["pr"] = pr_number

    def get_pr_from_commit(self, commit_sha: str):
        """Return the original PR data of a commit."""
        pr_number = None
        if commit_sha in self._commits_to_port["commits"]:
            pr_number = self._commits_to_port["commits"][commit_sha]["pr"]
        if pr_number:
            return self._commits_to_port["pull_requests"][str(pr_number)]
        return {}

    def get_commit_files(self, commit_sha: str):
        """Return file paths modified by a commit."""
        return self._commits_data[commit_sha].get("files", set())

    def set_commit_files(self, commit_sha: str, files: list):
        """Set file paths modified by a commit."""
        if self.readonly:
            return
        self._commits_data[commit_sha]["files"] = list(files)
        if os.environ.get("OCA_PORT_AGRESSIVE_CACHE_WRITE"):
            # IO can be very slow on some filesystems (like checking modified
            # paths of a commit), and saving the cache on each analyzed commit
            # could help in case current oca-port process is killed before
            # writing its cache on disk, so the next call will be faster.
            self._save_commits_data()

    def save(self):
        """Save cache files."""
        if self.readonly:
            return
        self._save_commits_to_port()
        self._save_commits_data()

    def _save_commits_to_port(self):
        # commits/PRs to port
        self._save_cache(self._commits_to_port, self._commits_to_port_path)

    def _save_commits_data(self):
        # commits data file
        self._save_cache(self._commits_data, self._commits_data_path)

    def _save_cache(self, cache, path):
        try:
            with path.open(mode="w") as file_:
                json.dump(cache, file_, indent=2)
        except Exception:
            pass

    def clear(self):
        """Clear the cache files."""
        paths = [
            self._ported_commits_path,
            self._commits_to_port_path,
            self._commits_data_path,
        ]
        for path in paths:
            if path and path.exists():
                path.unlink()
