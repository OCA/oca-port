import os
import pathlib
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import git

from oca_port.utils.misc import make_gh_info


class CommonCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.upstream_org = "ORG"
        cls.fork_org = "FORK"
        cls.repo_name = "test"
        cls.source1 = make_gh_info(
            "source", f"{cls.upstream_org}/{cls.repo_name}#15.0", remote="origin"
        )
        cls.source2 = make_gh_info(
            "source", f"{cls.upstream_org}/{cls.repo_name}#16.0", remote="origin"
        )
        cls.target1 = make_gh_info(
            "target", f"{cls.upstream_org}/{cls.repo_name}#16.0", remote="origin"
        )
        cls.target2 = make_gh_info(
            "target", f"{cls.upstream_org}/{cls.repo_name}#17.0", remote="origin"
        )
        cls.dest_branch = "dev"
        cls.destination = make_gh_info(
            "destination", f"{cls.fork_org}/{cls.repo_name}#{cls.dest_branch}"
        )
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
        repo.git.checkout("--orphan", self.source1.branch)
        os.makedirs(self.module_path, exist_ok=True)
        with open(self.manifest_path, "w") as manifest:
            manifest.writelines(tpl_manifest_lines)
        repo.index.add(self.manifest_path)
        commit = repo.index.commit(f"[ADD] {self.addon}")
        # Port the commit from 'branch1' to 'branch2'
        repo.git.checkout("--orphan", self.source2.branch)
        repo.git.reset("--hard")
        # FIXME without a delay, both branches are targeting the same commit,
        # no idea why.
        time.sleep(1)
        repo.git.cherry_pick(commit.hexsha)
        # Create an empty 'branch3'
        repo.git.checkout("--orphan", self.target2.branch)
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

    def tearDown(self):
        # Clean up the Git repository
        shutil.rmtree(self.repo_upstream_path)
        shutil.rmtree(self.repo_path)
