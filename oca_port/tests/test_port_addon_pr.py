import os
from unittest.mock import patch

from oca_port.port_addon_pr import PortAddonPullRequest
from oca_port.utils import git as g

from . import common


class TestPortAddonPullRequest(common.CommonCase):
    def _add_satellite_module(self, repo, branches):
        """Create 'test_my_module' on all `branches` of the upstream repository."""
        sat_path = self.repo_upstream_path / f"test_{self.addon}"
        for branch in branches:
            repo.git.checkout(branch)
            self._create_module(sat_path)
            repo.index.add([str(sat_path)])
            repo.index.commit(f"[ADD] test_{self.addon}")

    def _port_commit_updating_two_addons(self, target, direct=False, **kwargs):
        upstream = self._git_repo(self.repo_upstream_path)
        self._add_satellite_module(upstream, ["15.0", target.split("/")[1]])
        # One commit updating the manifests of my_module and test_my_module
        upstream.git.checkout("15.0")
        sat_manifest = (
            self.repo_upstream_path / f"test_{self.addon}" / "__manifest__.py"
        )
        sat_manifest.write_text(
            sat_manifest.read_text().replace('"base"', '"test_dependency"')
        )
        self.manifest_path.write_text(
            self.manifest_path.read_text().replace('"base"', '"sale"')
        )
        upstream.index.add([str(sat_manifest), str(self.manifest_path)])
        sha = upstream.index.commit(f"[FIX] {self.addon}, test_{self.addon}").hexsha

        app = self._create_app(self.source1, target, fetch=True, **kwargs)
        repo = self._git_repo(self.repo_path)
        repo.git.checkout("-b", "port", target)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo_path)
        commit = g.Commit(repo.commit(sha))
        pr = g.PullRequest(None, None, None, None, None, commits=[commit])
        port = PortAddonPullRequest(app, push_branch=False)
        if direct:
            port._apply_commit(commit, commit.paths_to_port)
        else:
            with patch("click.confirm", return_value=True):
                port._port_pull_request_commits(pr, [commit], target, "port")
        return repo

    def _assert_ported(self, repo, addon):
        # Each change lands in its own module
        self.assertFalse(repo.is_dirty())
        manifest = (self.repo_path / addon / "__manifest__.py").read_text()
        sat_manifest = (
            self.repo_path / f"test_{self.addon}" / "__manifest__.py"
        ).read_text()
        self.assertIn('"sale"', manifest)
        self.assertNotIn('"test_dependency"', manifest)
        self.assertIn('"test_dependency"', sat_manifest)

    def test_port_commit_updating_two_addons(self):
        repo = self._port_commit_updating_two_addons(self.target1)
        self._assert_ported(repo, self.addon)

    def test_port_commit_updating_two_addons_renamed(self):
        repo = self._port_commit_updating_two_addons(
            self.target3, direct=True, target_addon_path=self.target_addon
        )
        self._assert_ported(repo, self.target_addon)
