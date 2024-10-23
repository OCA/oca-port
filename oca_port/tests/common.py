import os
import pathlib
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from oca_port.app import App

import git


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
        cls.dest_branch = "dev"
        cls.destination = f"{cls.fork_org}/{cls.dest_branch}"
        cls.addon = "my_module"
        cls.no_cache = True

    def setUp(self):
        # Create a temporary Git repository
        self.repo_upstream_path = self._create_tmp_git_repository()
        self.module_path = os.path.join(self.repo_upstream_path, self.addon)
        self.manifest_path = os.path.join(self.module_path, "__manifest__.py")
        self._fill_git_repository(self.repo_upstream_path)
        # By cloning the first repository this will set an 'origin' remote
        self.repo_path = self._clone_tmp_git_repository(self.repo_upstream_path)
        self._add_fork_remote(self.repo_path)
        # Patch GitHub class to prevent sending HTTP requests
        self._patch_github_class()

    def _patch_github_class(self):
        self.patcher = patch("oca_port.app.GitHub.request")
        github_request = self.patcher.start()
        github_request.return_value = {}
        self.addCleanup(self.patcher.stop)

    def _create_tmp_git_repository(self):
        """Create a temporary Git repository to run tests."""
        repo_path = tempfile.mkdtemp()
        git.Repo.init(repo_path)
        return repo_path

    def _clone_tmp_git_repository(self, upstream_path):
        repo_path = tempfile.mkdtemp()
        git.Repo.clone_from(upstream_path, repo_path)
        return repo_path

    def _git_repo(self, repo_path):
        return git.Repo(repo_path)

    def _fill_git_repository(self, repo_path):
        """Create branches with some content in the Git repository."""
        repo = git.Repo(repo_path)
        tpl_manifest_path = os.path.join(
            pathlib.Path(__file__).parent.resolve(),
            "data",
            "manifest.py",
        )
        with open(tpl_manifest_path) as tpl_manifest:
            tpl_manifest_lines = tpl_manifest.readlines()
        # Commit a file in '15.0'
        branch1 = self.source1.split("/")[1]
        repo.git.checkout("--orphan", branch1)
        os.makedirs(self.module_path, exist_ok=True)
        with open(self.manifest_path, "w") as manifest:
            manifest.writelines(tpl_manifest_lines)
        repo.index.add(self.manifest_path)
        commit = repo.index.commit(f"[ADD] {self.addon}")
        # Port the commit from 'branch1' to 'branch2'
        branch2 = self.source2.split("/")[1]
        repo.git.checkout("--orphan", branch2)
        repo.git.reset("--hard")
        # FIXME without a delay, both branches are targeting the same commit,
        # no idea why.
        time.sleep(1)
        repo.git.cherry_pick(commit.hexsha)
        # Create an empty 'branch3'
        branch3 = self.target2.split("/")[1]
        repo.git.checkout("--orphan", branch3)
        repo.git.reset("--hard")
        repo.git.commit("-m", "Init", "--allow-empty")

    def _add_fork_remote(self, repo_path):
        repo = git.Repo(repo_path)
        # We do not really care about the remote URL here, re-use origin one
        repo.create_remote(self.fork_org, repo.remotes.origin.url)

    def _commit_change_on_branch(self, repo_path, branch):
        """Commit a change that can be ported to another branch."""
        repo = git.Repo(repo_path)
        repo.git.checkout(branch)
        # Do some changes and commit
        with open(self.manifest_path, "r+") as manifest:
            content = manifest.read()
            content = content.replace('"base"', '"sale"')
            manifest.seek(0)
            manifest.write(content)
        repo.index.add(self.manifest_path)
        commit = repo.index.commit(f"[FIX] {self.addon}: fix dependency")
        return commit.hexsha

    def _create_app(self, source, target, destination=None, **kwargs):
        params = {
            "source": source,
            "target": target,
            "destination": destination,
            "addon": self.addon,
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
