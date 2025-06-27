# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import contextlib
import pathlib
import re
import subprocess
from collections import abc

import git as g

from . import misc
from .misc import bcolors as bc, pr_ref_from_url

PO_FILE_REGEX = re.compile(r".*i18n/.+\.pot?$")


class Branch:
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

    def __new__(cls, addons_path, value, eq_paths=None):
        if not eq_paths:
            eq_paths = {}
        file_path = pathlib.Path(value).relative_to(addons_path)
        root_node = file_path.parts[0]
        if eq_paths.get(root_node):
            root_node = eq_paths[root_node]
        obj = super().__new__(cls, root_node)
        # As soon as `file_path` has a parent, the root node is obviously a folder
        obj.isdir = bool(file_path.parent.name)
        return obj


class Commit:
    # Attributes used to check equality between commits.
    # We do not want to use the SHA here as it changed from one branch to another
    # when a commit is ported (obviously).
    base_equality_attrs = (
        "author_name",
        "author_email",
        "authored_datetime",
        "message",
    )
    other_equality_attrs = ("paths",)
    eq_strict = True

    def __init__(self, commit, addons_path=".", eq_paths=None, cache=None):
        """Initializes a new Commit instance from a GitPython Commit object.

        `eq_paths` is used to declare equivalent paths, to ease commits
        comparison. This is a mapping `{'my_module': 'new_module', ...}`.
        """
        self.raw_commit = commit
        self.addons_path = addons_path
        self.cache = cache
        self.author_name = commit.author.name
        self.author_email = commit.author.email
        self.authored_datetime = commit.authored_datetime.replace(
            tzinfo=None
        ).isoformat()
        self.summary = commit.summary
        self.message = commit.message.strip()
        self.hexsha = commit.hexsha
        self.committed_datetime = commit.committed_datetime.replace(tzinfo=None)
        self.parents = [parent.hexsha for parent in commit.parents]
        self._files = set()
        self._paths = set()
        self.eq_paths = {}
        if eq_paths:
            # If a == b, then b == a
            inv_eq_paths = {v: k for k, v in eq_paths.items()}
            eq_paths.update(inv_eq_paths)
            self.eq_paths = eq_paths
        self.ported_commits = []

    @property
    def files(self):
        """Returns modified file paths."""
        # Access git storage or cache only on demand to avoid too much IO
        files = self._get_files()
        if not self._files:
            self._files = files
        return self._files

    @property
    def paths(self):
        """Return the folders/files updated in `addons_path`.

        If a commit updates files 'x/a/b/c.py', 'x/d/e.py' and 'x/f.txt', knowing
        the `addons_path` is `x`, the root nodes updated by this commit are
        `a` (folder), `d` (folder) and `f.txt` (file).
        """
        if self._paths:
            return self._paths
        self._paths = set()
        for f in self.files:
            # Could raise "ValueError: 'f' is not in the subpath of 'addons_path'"
            # in such case we ignore these files, and keep ones in 'addons_path'
            try:
                commit_path = CommitPath(self.addons_path, f)
                eq_commit_path = CommitPath(self.addons_path, f, eq_paths=self.eq_paths)
            except ValueError:
                continue
            self._paths.add(commit_path)
            self._paths.add(eq_commit_path)
        return self._paths

    def _get_files(self):
        """Retrieve file paths modified by this commit.

        Leverage the user's cache if one is provided as git can be quite slow
        to retrieve such data from big repository.
        """
        files = set()
        if self.cache:
            files = self.cache.get_commit_files(self.hexsha)
        if not files:
            files = {
                f for f in set(self.raw_commit.stats.files.keys()) if "=>" not in f
            }
            if self.cache:
                self.cache.set_commit_files(self.hexsha, files)
        return files

    def _get_equality_attrs(self):
        return [attr for attr in self.base_equality_attrs if hasattr(self, attr)] + [
            attr
            for attr in self.other_equality_attrs
            if self.__class__.eq_strict and hasattr(self, attr)
        ]

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
        return misc.clean_text(self_value) == misc.clean_text(other_value)

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
                any(manifest in diff.b_path for manifest in misc.MANIFEST_NAMES)
                and diff.change_type == "A"
            ):
                addons.add(diff.b_path.split("/", maxsplit=1)[0])
        return addons

    @property
    def paths_to_port(self):
        """Return the list of file paths to port."""
        current_paths = {
            diff.a_path
            for diff in self.diffs
            if self._keep_diff_path(diff, diff.a_path)
        }.union(
            {
                diff.b_path
                for diff in self.diffs
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
        return self.raw_commit.diff(g.NULL_TREE)


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
        self,
        number,
        url,
        author,
        title,
        body,
        merged_at=None,
        commits=None,
        paths=None,
        ported_paths=None,
    ):
        self.number = number
        self.url = url
        self.ref = pr_ref_from_url(url)
        self.author = author
        self.title = title
        self.body = body
        self.merged_at = merged_at
        self.commits = commits if commits else []
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

    def to_dict(self, ref=True, number=False, body=False, commits=False):
        data = {
            "url": self.url,
            "author": self.author,
            "title": self.title,
            "merged_at": str(self.merged_at or ""),
        }
        if ref:
            data["ref"] = self.ref
        if number:
            data["number"] = self.number
        if body:
            data["body"] = self.body
        if commits:
            data["commits"] = self.commits
        return data


def run_pre_commit(repo, hook=None):
    """Run pre-commit and returns updated file paths."""
    print(f"\tRun {bc.BOLD}pre-commit{bc.END}...")
    if repo.is_dirty(index=False):
        raise RuntimeError("Unstaged changes detected. pre-commit execution aborted.")
    untracked_files = set(repo.untracked_files)
    # First ensure that 'pre-commit' is initialized for the repository,
    # then run it (without checking the return code on purpose)
    subprocess.check_call("pre-commit install", shell=True)
    if hook:
        subprocess.run(f"pre-commit run {hook}", shell=True)
    else:
        subprocess.run("pre-commit run -a", shell=True)
    new_untracked_files = set(repo.untracked_files)
    changed_files = {diff.a_path for diff in repo.index.diff(None)}
    updated_files = (new_untracked_files | changed_files) - untracked_files
    return updated_files


def commit(repo, msg, paths=None, no_verify=True):
    """Commit `paths` (or all files if not set)."""
    paths = paths or []
    repo.git.add("-A", *paths)
    repo.git.commit("-m", msg, "--no-verify" if no_verify else "")


def get_changed_paths(repo, modified=True, staged=True):
    """Return a list of file paths that have been changed.

    :param modified: include modified files (not added to the index)
    :param staged: include staged files (added to the index)
    :return: list of changed file paths
    """
    changed_diff = []
    if modified:
        changed_diff.extend(repo.index.diff(None))
    if staged:
        changed_diff.extend(repo.index.diff("HEAD"))
    return [diff.a_path or diff.b_path for diff in changed_diff]


def check_path_exists(repo, ref, path, rootdir=None):
    root_tree = repo.commit(ref).tree
    if rootdir and rootdir != ".":
        root_tree /= str(rootdir)
    paths = [t.path for t in root_tree.trees]
    return path in paths
