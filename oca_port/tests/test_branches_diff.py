import os
import tempfile

from oca_port.port_addon_pr import BranchesDiff
from oca_port.utils.misc import extract_ref_info

from . import common


class TestBranchesDiff(common.CommonCase):
    def test_without_satellite_changes(self):
        repo = self._git_repo(self.repo_path)
        source1 = extract_ref_info(repo, "source", self.source1)
        self._commit_change_on_branch(self.repo_upstream_path, source1.branch)
        app = self._create_app(self.source1, self.target1)
        diff = BranchesDiff(app)
        self.assertFalse(diff.commits_diff["addon"])
        self.assertFalse(diff.commits_diff["satellite"])

    def test_with_satellite_changes(self):
        repo = self._git_repo(self.repo_path)
        source1 = extract_ref_info(repo, "source", self.source1)
        # Add a change in another module but in the same commit
        change_sha = self._commit_change_on_branch(
            self.repo_upstream_path, source1.branch, add_satellite_change=True
        )
        # Port only the commit content related to the analyzed module
        upstream_repo = self._git_repo(self.repo_upstream_path)
        upstream_repo.git.checkout("16.0")
        patches_dir = tempfile.mkdtemp()
        upstream_repo.git.format_patch(
            "--keep-subject",
            "-o",
            patches_dir,
            "-1",
            change_sha,
            "--",
            self.addon,
        )
        patches = [
            os.path.join(patches_dir, f) for f in sorted(os.listdir(patches_dir))
        ]
        upstream_repo.git.am("-3", "--keep", *patches)
        # Check if unported change is detected as satellite
        app = self._create_app(self.source1, self.target1, fetch=True)
        diff = BranchesDiff(app)
        self.assertFalse(diff.commits_diff["addon"])
        self.assertTrue(diff.commits_diff["satellite"])
        self.assertEqual(
            list(diff.commits_diff["satellite"].values())[0][0].hexsha, change_sha
        )
