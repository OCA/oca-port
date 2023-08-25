# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import json
import os
import pathlib
from collections import defaultdict

import click

from . import git as g, misc


class InputStorage:
    """Store the user inputs related to an addon.

    If commits/pull requests of an addon may be ported, some of them could be
    false-positive and as such the user can choose to not port them.
    This class will help to store these informations so the tool won't list
    anymore these commits the next time we perform an analysis on the same addon.

    Technically the data are stored in one JSON file per addon in a hidden
    folder at the root of the repository. E.g:

        {
          "no_migration": "included in standard"
        }

    Or:

        {
          "pull_requests": {
            "OCA/repo#490": "lint changes"
          }
        }
    """

    __slots__ = (
        "to_branch",
        "repo",
        "root_path",
        "addon",
        "dirty",
        "ensure_storage_committed",
        "_data",
        "_is_staged",
    )

    storage_dirname = ".oca/oca-port"

    def __init__(self, to_branch, addon):
        self.to_branch = to_branch
        self.repo = self.to_branch.repo
        self.root_path = pathlib.Path(self.repo.working_dir)
        self.addon = addon
        self.dirty = False
        self._data, self._is_staged = self._get_data()

    def _get_data(self):
        """Return the data of the current repository.

        If a JSON file is found, return its content, otherwise return an empty
        dictionary.
        """
        # Read the JSON file from 'to_branch'
        is_staged = False
        try:
            # This is important because the analysis of the branch
            # can be done on non-checked out branches
            # and we still want to read the file from there.
            tree = self.repo.commit(self.to_branch.ref()).tree
            # When the file is not there, this throws a KeyError
            blob = tree / self.storage_dirname / "blacklist" / f"{self.addon}.json"
            content = blob.data_stream.read().decode()
            is_staged = True
        except KeyError:
            # We might have a local path not committed
            path = self._get_file_path()
            if not path:
                return self._get_default_data(), is_staged
            with path.open() as fd:
                content = fd.read() or "{}"
        return json.loads(content, object_hook=misc.defaultdict_from_dict), is_staged

    def _get_default_data(self):
        nested_dict = lambda: defaultdict(nested_dict)  # noqa
        return nested_dict()

    def save(self):
        """Store the data at the root of the current repository."""
        if not self._data or not self.dirty:
            return False
        file_path = self._get_file_path(ignore_missing=True)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as file_:
            json.dump(self._data, file_, indent=2)
        return True

    def _get_file_path(self, ignore_missing=False):
        override = self._get_file_path_override()
        if override:
            return override
        filepath = (
            self.root_path / self.storage_dirname / "blacklist" / f"{self.addon}.json"
        )
        if ignore_missing:
            return filepath
        if filepath.exists():
            return filepath

    def _get_file_path_override(self):
        if os.getenv("BLACKLIST_FILE"):
            return pathlib.Path(os.getenv("BLACKLIST_FILE"))

    def is_pr_blacklisted(self, pr_ref):
        pr_ref = str(pr_ref or "orphaned_commits")
        return self._data.get("pull_requests", {}).get(pr_ref, False)

    def blacklist_pr(self, pr_ref, confirm=False, reason=None):
        if confirm and not click.confirm("\tBlacklist this PR?"):
            return
        if not reason:
            reason = click.prompt("\tReason", type=str)
        pr_ref = str(pr_ref or "orphaned_commits")
        self._data["pull_requests"][pr_ref] = reason or "Unknown"
        self.dirty = True

    def is_addon_blacklisted(self):
        entry = self._data.get("no_migration")
        if entry:
            return entry
        return False

    def blacklist_addon(self, confirm=False, reason=None):
        if confirm and not click.confirm("\tBlacklist this module?"):
            return
        if not reason:
            reason = click.prompt("Reason", type=str)
        self._data["no_migration"] = reason or "Unknown"
        self.dirty = True

    def commit(self, msg=None):
        """Commit all files contained in the storage directory."""
        if not self.save():
            return
        if not self._is_staged:
            # Likely a custom non staged file is used
            return
        changed_paths = g.get_changed_paths(self.repo)
        all_in_storage = all(
            path.startswith(self.storage_dirname) for path in changed_paths
        )
        if self.repo.is_dirty() and not all_in_storage:
            raise click.ClickException(
                "changes not committed detected in this repository."
            )
        # Ensure to be on a dedicated branch
        if self.repo.active_branch.name == self.to_branch.name:
            raise click.ClickException(
                "performing commit on upstream branch is not allowed."
            )
        # Commit all changes under ./.oca-port
        self.repo.index.add(self.storage_dirname)
        if self.repo.is_dirty():
            g.run_pre_commit(self.repo, self.addon, commit=False, hook="prettier")
            self.repo.index.commit(msg or f"oca-port: store '{self.addon}' data")
            self.dirty = False
