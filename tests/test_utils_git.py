# Copyright 2023 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import git

from oca_port.utils import git as g

from . import common


class TestUtilsGit(common.CommonCase):
    def test_branch(self):
        repo = git.Repo(self.repo_path)
        branch = g.Branch(repo, "test")
        # Checkout: does nothing as branch doesn't exist in the repo
        self.assertFalse(branch.exists())
        branch.checkout()
        self.assertFalse(branch.exists())
        # Checkout: does nothing as branch doesn't exist in the repo
        branch.checkout(create=True)
        self.assertTrue(branch.exists())
        # ref == branch name as no remote
        self.assertEqual(branch.ref(), branch.name)

    def test_branch_with_base_ref(self):
        repo = git.Repo(self.repo_path)
        branch = g.Branch(repo, "test", base_ref="origin/16.0")
        # Checkout: does nothing as branch doesn't exist in the repo
        self.assertFalse(branch.exists())
        branch.checkout()
        self.assertFalse(branch.exists())
        # Create the branch
        branch.checkout(create=True)
        self.assertTrue(branch.exists())

    def test_branch_with_remote(self):
        repo = git.Repo(self.repo_path)
        # Check a branch that doesn't exist upstream
        branch = g.Branch(repo, "test", default_remote="origin")
        self.assertEqual(branch.ref(), branch.name)
        # Check a branch that exists upstream
        branch = g.Branch(repo, "17.0", default_remote="origin")
        self.assertEqual(branch.ref(), f"origin/{branch.name}")
