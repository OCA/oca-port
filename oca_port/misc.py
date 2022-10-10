# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

from collections import abc, defaultdict
import contextlib
import json
import re
import os
import subprocess

import click
import git
import requests

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


GITHUB_API_URL = "https://api.github.com"

PO_FILE_REGEX = re.compile(r".*i18n/.+\.pot?$")


# Copy-pasted from OCA/maintainer-tools
def get_manifest_path(addon_dir):
    for manifest_name in MANIFEST_NAMES:
        manifest_path = os.path.join(addon_dir, manifest_name)
        if os.path.isfile(manifest_path):
            return manifest_path


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = '\033[96m'
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[39m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ENDD = "\033[22m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


class Branch():
    def __init__(self, repo, name, default_remote=None, check_remote=True):
        self.repo = repo
        if len(name.split("/", 1)) > 1:
            remote, name = name.split("/", 1)
        else:
            remote = default_remote
        self.name = name
        self.remote = None
        if remote:
            if check_remote and remote not in repo.remotes:
                raise ValueError(repo, remote)
            self.remote = remote

    def ref(self):
        ref = self.name
        if self.remote:
            ref = f"{self.remote}/{self.name}"
        return ref


class CommitPath(str):
    """Helper class to know if a base path is a directory or a file."""
    def __new__(cls, value):
        new_value = value.split("/", maxsplit=1)[0]
        obj = super().__new__(cls, new_value)
        obj.isdir = "/" in value
        return obj


class Commit():
    # Attributes used to check equality between commits.
    # We do not want to use the SHA here as it changed from one branch to another
    # when a commit is ported (obviously).
    base_equality_attrs = (
        "author_name",
        "author_email",
        "authored_datetime",
        "message",
    )
    other_equality_attrs = (
        "paths",
    )
    eq_strict = True

    def __init__(self, commit):
        """Initializes a new Commit instance from a GitPython Commit object."""
        self.raw_commit = commit
        self.author_name = commit.author.name
        self.author_email = commit.author.email
        self.authored_datetime = commit.authored_datetime.replace(
            tzinfo=None
        ).isoformat()
        self.summary = commit.summary
        self.message = commit.message
        self.hexsha = commit.hexsha
        self.committed_datetime = commit.committed_datetime.replace(tzinfo=None)
        self.parents = [parent.hexsha for parent in commit.parents]
        self.files = {f for f in set(commit.stats.files.keys()) if "=>" not in f}
        self.paths = {CommitPath(f) for f in self.files}
        self.ported_commits = []

    def _get_equality_attrs(self):
        return (
            [attr for attr in self.base_equality_attrs if hasattr(self, attr)]
            +
            [
                attr for attr in self.other_equality_attrs
                if self.__class__.eq_strict and hasattr(self, attr)
            ]
        )

    def _lazy_eq_message(self, other):
        """Compare commit messages."""
        # If the subject has been put on two lines, 'git-am' won't preserve it
        # if '--keep-cr' option is not set, this generates false-positive.
        # Replace all carriage returns and double spaces by one space character
        # when performing the comparison.
        self_value = self.message.replace("\n", " ").replace("  ", " ")
        other_value = other.message.replace("\n", " ").replace("  ", " ")
        # 'git am' without '--keep' option removes text in '[]' brackets
        # generating false-positive.
        return clean_text(self_value) == clean_text(other_value)

    def __eq__(self, other):
        """Consider a commit equal to another if some of its keys are the same."""
        if not isinstance(other, Commit):
            return super().__eq__(other)
        if self.__class__.eq_strict:
            return all(
                [
                    getattr(self, attr) == getattr(other, attr)
                    for attr in self._get_equality_attrs()
                ]
            )
        else:
            checks = [
                (
                    self._lazy_eq_message(other)
                    if attr == "message"
                    else getattr(self, attr) == getattr(other, attr)
                )
                for attr in self._get_equality_attrs()
            ]
            return all(checks)

    def __repr__(self):
        attrs = ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])
        return f"{self.__class__.__name__}({attrs})"

    @property
    def addons_created(self):
        """Returns the list of addons created by this commit."""
        addons = set()
        for diff in self.diffs:
            if (
                    any(manifest in diff.b_path for manifest in MANIFEST_NAMES)
                    and diff.change_type == "A"
                    ):
                addons.add(diff.b_path.split("/", maxsplit=1)[0])
        return addons

    @property
    def paths_to_port(self):
        """Return the list of file paths to port."""
        current_paths = {
            diff.a_path for diff in self.diffs
            if self._keep_diff_path(diff, diff.a_path)
        }.union(
            {
                diff.b_path for diff in self.diffs
                if self._keep_diff_path(diff, diff.b_path)
            }
        )
        ported_paths = set()
        for ported_commit in self.ported_commits:
            for diff in ported_commit.diffs:
                ported_paths.add(diff.a_path)
                ported_paths.add(diff.b_path)
        return current_paths - ported_paths

    def _keep_diff_path(self, diff, path):
        """Check if a file path should be ported."""
        # Ignore 'setup' files
        if path.startswith("setup"):
            return False
        # Ignore changes on po/pot files
        if PO_FILE_REGEX.match(path):
            return False
        return True

    @property
    def diffs(self):
        if self.raw_commit.parents:
            return self.raw_commit.diff(self.raw_commit.parents[0], R=True)
        return self.raw_commit.diff(git.NULL_TREE)


@contextlib.contextmanager
def no_strict_commit_equality():
    try:
        Commit.eq_strict = False
        yield
    finally:
        Commit.eq_strict = True


class PullRequest(abc.Hashable):
    eq_attrs = ("number", "url", "author", "title", "body", "merged_at")

    def __init__(
            self, number, url, author, title, body, merged_at,
            paths=None, ported_paths=None
            ):
        self.number = number
        self.url = url
        self.author = author
        self.title = title
        self.body = body
        self.merged_at = merged_at
        self.paths = set(paths) if paths else set()
        self.ported_paths = set(ported_paths) if ported_paths else set()

    def __eq__(self, other):
        if not isinstance(other, PullRequest):
            return super().__eq__(other)
        return all(
            [
                getattr(self, attr) == getattr(other, attr)
                for attr in self.__class__.eq_attrs
            ]
        )

    def __hash__(self):
        attr_values = tuple(getattr(self, attr) for attr in self.eq_attrs)
        return hash(attr_values)

    @property
    def paths_not_ported(self):
        return list(self.paths - self.ported_paths)


class InputStorage():
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
            490: "lint changes"
          }
        }
    """
    storage_dirname = ".oca/oca-port"

    def __init__(self, to_branch, addon):
        self.to_branch = to_branch
        self.repo = self.to_branch.repo
        self.root_path = self.repo.working_dir
        self.addon = addon
        self._data = self._get_data()
        self.dirty = False

    def _get_data(self):
        """Return the data of the current repository.

        If a JSON file is found, return its content, otherwise return an empty
        dictionary.
        """

        def defaultdict_from_dict(d):
            nd = lambda: defaultdict(nd)    # noqa
            ni = nd()
            ni.update(d)
            return ni

        try:
            # Read the JSON file from 'to_branch'
            tree = self.repo.commit(self.to_branch.ref()).tree
            blob = tree/self.storage_dirname/"blacklist"/f"{self.addon}.json"
            content = blob.data_stream.read().decode()
            return json.loads(content, object_hook=defaultdict_from_dict)
        except KeyError:
            nested_dict = lambda: defaultdict(nested_dict)  # noqa
            return nested_dict()

    def save(self):
        """Store the data at the root of the current repository."""
        if not self._data or not self.dirty:
            return False
        file_path = self._get_file_path()
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as file_:
            json.dump(self._data, file_, indent=2)
        return True

    def _get_file_path(self):
        return os.path.join(
            self.root_path, self.storage_dirname, "blacklist", f"{self.addon}.json"
        )

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

    def commit(self):
        """Commit all files contained in the storage directory."""
        if not self.save():
            return
        if self.repo.is_dirty():
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
            run_pre_commit(self.repo, self.addon, commit=False, hook="prettier")
            self.repo.index.commit(f"oca-port: store '{self.addon}' data")
            self.dirty = False


def clean_text(text):
    """Clean text by removing patterns like '13.0', '[13.0]' or '[IMP]'."""
    return re.sub(r"\[.*\]|\d+\.\d+", "", text).strip()


def _request_github(url, method="get", params=None, json=None):
    """Request GitHub API."""
    headers = {"Accept": "application/vnd.github.groot-preview+json"}
    if os.environ.get("GITHUB_TOKEN"):
        token = os.environ.get("GITHUB_TOKEN")
        headers.update({"Authorization": f"token {token}"})
    full_url = "/".join([GITHUB_API_URL, url])
    kwargs = {"headers": headers}
    if json:
        kwargs.update(json=json)
    if params:
        kwargs.update(params=params)
    response = getattr(requests, method)(full_url, **kwargs)
    if not response.ok:
        raise RuntimeError(response.text)
    return response.json()


def run_pre_commit(repo, addon, commit=True, hook=None):
    # Run pre-commit
    print(
        f"\tRun {bcolors.BOLD}pre-commit{bcolors.END} and commit changes if any..."
    )
    # First ensure that 'pre-commit' is initialized for the repository,
    # then run it (without checking the return code on purpose)
    subprocess.check_call("pre-commit install", shell=True)
    if hook:
        subprocess.run(f"pre-commit run {hook}", shell=True)
    else:
        subprocess.run("pre-commit run -a", shell=True)
    if repo.untracked_files or repo.is_dirty():
        repo.git.add("-A")
        if commit:
            repo.git.commit(
                "-m", f"[IMP] {addon}: black, isort, prettier", "--no-verify"
            )
