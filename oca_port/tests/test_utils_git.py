# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from collections import namedtuple


from . import common

from oca_port.utils import git as g

FakeCommit = namedtuple(
    "FakeCommit",
    [
        "author",
        "authored_datetime",
        "summary",
        "message",
        "hexsha",
        "committed_datetime",
        "parents",
        "stats",
    ],
)

FakeAuthor = namedtuple("FakeAuthor", ["name", "email"])


class TestGit(common.CommonCase):
    def setUp(self):
        super().setUp()
        self.repo = self._git_repo(self.repo_upstream_path)
        self.branch1 = self.source1.split("/")[1]
        self.branch2 = self.source2.split("/")[1]

    def test_same_commit_eq(self):
        raw_commit = self.repo.refs[self.branch1].commit
        c1 = g.Commit(raw_commit)
        c2 = g.Commit(raw_commit)
        self.assertEqual(c1, c2)

    def test_different_commit_not_eq(self):
        raw_commit1 = self.repo.refs["17.0"].commit
        # On 18.0 branch, last commit is renaming a module,
        # so different than last commit on 17.0
        raw_commit2 = self.repo.refs["18.0"].commit
        c1 = g.Commit(raw_commit1)
        c2 = g.Commit(raw_commit2)
        self.assertNotEqual(c1, c2)

    def test_different_commit_eq(self):
        raw_commit1_sha = self._commit_change_on_branch(
            self.repo_upstream_path, self.branch1
        )
        raw_commit1 = self.repo.commit(raw_commit1_sha)
        raw_commit2_sha = self._commit_change_on_branch(
            self.repo_upstream_path, self.branch2
        )
        raw_commit2 = self.repo.commit(raw_commit2_sha)
        c1 = g.Commit(raw_commit1)
        c2 = g.Commit(raw_commit2)
        self.assertEqual(c1, c2)

    def test_different_commit_eq_paths(self):
        """Test commit comparison on a module renamed with 'git mv'."""
        # Commit "[ADD] my_module"
        raw_commit1 = self.repo.refs[self.branch1].commit
        # Create the same commit through a cherry-pick + amend to rename the
        # module, but all other commit attributes are the same
        self.repo.git.checkout("--orphan", "TEST")
        self.repo.git.reset("--hard")
        self.repo.git.cherry_pick(raw_commit1.hexsha)
        self.repo.git.mv(self.addon, self.target_addon)
        self.repo.git.commit("--amend", "--no-edit")
        raw_commit2 = self.repo.refs["TEST"].commit
        # Compare them
        eq_paths = {self.addon: self.target_addon}
        c1 = g.Commit(raw_commit1, eq_paths=eq_paths)
        c2 = g.Commit(raw_commit2, eq_paths=eq_paths)
        self.assertEqual(c1, c2)
        self.assertEqual(c1.paths, c2.paths)
        self.assertNotEqual(c1.files, c2.files)  # Different file paths updated
