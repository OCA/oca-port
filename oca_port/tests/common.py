# Copyright 2026 Sébastien Alix
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
import io
import pathlib
import shutil
import tempfile
import time
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from oca_port.app import App

import git

cache = threading.local()


class CommonCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.upstream_org = "ORG"
        cls.fork_org = "FORK"
        cls.repo_name = "test"
        cls.source1 = "origin/15.0"
        cls.source2 = "origin/16.0"
        cls.target1 = "origin/16.0"
        cls.target2 = "origin/17.0"
        cls.target3 = "origin/18.0"
        cls.dest_branch = "dev"
        cls.destination = f"{cls.fork_org}/{cls.dest_branch}"
        cls.addon = "my_module"
        cls.target_addon = "my_module_renamed"
        cls.no_cache = True

    def setUp(self):
        # Create a temporary Git repository
        self.repo_upstream_path = self._get_upstream_repository_path()
        self.addon_path = Path(self.repo_upstream_path) / self.addon
        self.target_addon_path = self.repo_upstream_path / self.target_addon
        self.manifest_path = self.addon_path / "__manifest__.py"
        # By cloning the first repository this will set an 'origin' remote
        self.repo_path = self._clone_tmp_git_repository(self.repo_upstream_path)
        self._add_fork_remote(self.repo_path)
        # Patch GitHub class to prevent sending HTTP requests
        self._patch_github_class()

    def _get_upstream_repository_path(self) -> Path:
        """Returns the path of upstream repository.

        Generate the upstream git repository or re-use the one put in cache if any.
        """
        if hasattr(cache, "archive_data") and cache.archive_data:
            # Unarchive the repository from memory
            repo_path = self._unarchive_upstream_repository(cache.archive_data)
        else:
            # Prepare and archive the repository in memory
            repo_path = self._create_tmp_git_repository()
            addon_path = repo_path / self.addon
            self._fill_git_repository(repo_path, addon_path)
            cache.archive_data = self._archive_upstream_repository(repo_path)
        return repo_path

    def _archive_upstream_repository(self, repo_path: Path) -> bytes:
        """Archive the repository located at `repo_path`.

        Returns binary value of the archive.
        """
        # Create in-memory zip archive
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for file_path in repo_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(repo_path)
                    zipf.write(file_path, arcname)
        return zip_buffer.getvalue()

    def _unarchive_upstream_repository(self, archive_data: bytes) -> Path:
        """Unarchive the repository contained in `archive_data`.

        Returns path of repository.
        """
        temp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(io.BytesIO(archive_data), "r") as zip_ref:
            zip_ref.extractall(temp_dir)
        # Look for the repo directory and return its path
        for path in Path(temp_dir).rglob("*"):
            if path.is_dir() and path.name == ".git":
                return path.parent

    def _patch_github_class(self):
        self.patcher = patch("oca_port.app.GitHub.request")
        github_request = self.patcher.start()
        github_request.return_value = {}
        self.addCleanup(self.patcher.stop)

    def _create_tmp_git_repository(self) -> Path:
        """Create a temporary Git repository to run tests."""
        repo_path = tempfile.mkdtemp()
        git.Repo.init(repo_path)
        return Path(repo_path)

    def _clone_tmp_git_repository(self, upstream_path: Path) -> Path:
        repo_path = tempfile.mkdtemp()
        git.Repo.clone_from(upstream_path, repo_path)
        return Path(repo_path)

    def _git_repo(self, repo_path):
        return git.Repo(repo_path)

    def _fill_git_repository(self, repo_path: Path, addon_path: Path):
        """Create branches with some content in the Git repository."""
        repo = git.Repo(repo_path)
        # Commit a file in '15.0'
        branch1 = self.source1.split("/")[1]
        repo.git.checkout("--orphan", branch1)
        self._create_module(addon_path)
        repo.index.add(addon_path)
        commit = repo.index.commit(f"[ADD] {self.addon}")
        # Port the commit from 15.0 to 16.0
        branch2 = self.source2.split("/")[1]
        repo.git.checkout("--orphan", branch2)
        repo.git.reset("--hard")
        # FIXME without a delay, both branches are targeting the same commit,
        # no idea why.
        time.sleep(1)
        repo.git.cherry_pick(commit.hexsha)
        # Create an empty branch 17.0
        branch3 = self.target2.split("/")[1]
        repo.git.checkout("--orphan", branch3)
        repo.git.reset("--hard")
        repo.git.commit("-m", "Init", "--allow-empty")
        # Port the commit from 15.0 to 18.0
        branch3 = self.target3.split("/")[1]
        repo.git.checkout("--orphan", branch3)
        repo.git.reset("--hard")
        time.sleep(1)
        repo.git.cherry_pick(commit.hexsha)
        # Rename the module on 18.0
        repo.git.mv(self.addon, self.target_addon)
        repo.git.commit("-m", f"Rename {self.addon} to {self.target_addon}")

    def _create_module(self, module_path: Path):
        tpl_manifest_path = (
            pathlib.Path(__file__).parent.resolve() / "data" / "manifest.py"
        )
        with open(tpl_manifest_path) as tpl_manifest:
            tpl_manifest_lines = tpl_manifest.readlines()
        module_path.mkdir(parents=True, exist_ok=True)
        manifest_path = module_path / "__manifest__.py"
        with open(manifest_path, "w") as manifest:
            manifest.writelines(tpl_manifest_lines)

    def _add_fork_remote(self, repo_path: Path):
        repo = git.Repo(repo_path)
        # We do not really care about the remote URL here, re-use origin one
        repo.create_remote(self.fork_org, repo.remotes.origin.url)

    def _commit_change_on_branch(self, repo_path, branch, add_satellite_change=False):
        """Commit a change that can be ported to another branch."""
        repo = git.Repo(repo_path)
        repo.git.checkout(branch)
        # Do some changes in existing modules
        with open(self.manifest_path, "r+") as manifest:
            content = manifest.read()
            content = content.replace('"base"', '"sale"')
            manifest.seek(0)
            manifest.write(content)
        repo.index.add(self.manifest_path)
        # Create a new module in the same commit
        if add_satellite_change:
            module_path = self.repo_upstream_path / f"test_{self.addon}"
            self._create_module(module_path)
            repo.index.add(module_path)
        # Commit
        commit = repo.index.commit(f"[FIX] {self.addon}: fix dependency")
        return commit.hexsha

    def _create_app(self, source, target, destination=None, **kwargs):
        params = {
            "source": source,
            "target": target,
            "destination": destination,
            "addon_path": self.addon,
            "source_version": None,
            "target_version": None,
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "no_cache": self.no_cache,
        }
        params.update(kwargs)
        return App(**params)

    def tearDown(self):
        # Clean up the Git repository
        shutil.rmtree(self.repo_upstream_path)
        shutil.rmtree(self.repo_path)
