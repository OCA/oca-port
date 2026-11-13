from unittest.mock import patch

from oca_port.migrate_addon import MigrateAddon
from oca_port.utils.misc import extract_ref_info

from . import common


class TestMigrateAddon(common.CommonCase):
    def test_usual_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips()
        self.assertIn("1) Reduce the number of commits", tips)
        self.assertIn("2) Adapt the module", tips)
        self.assertIn("3) On a shell command", tips)
        self.assertIn("4) Create the PR against", tips)
        self.assertNotIn("5) ", tips)

    def test_blacklist_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips(blacklisted=True)
        self.assertIn("1) On a shell command", tips)
        self.assertIn("2) Create the PR against", tips)
        self.assertNotIn("3) ", tips)

    def test_adapted_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips(adapted=True)
        self.assertIn("1) Reduce the number of commits", tips)
        self.assertIn("2) Adapt the module", tips)
        self.assertIn("3) Include your changes", tips)
        self.assertIn("4) Create the PR against", tips)
        self.assertNotIn("5) ", tips)

    def test_already_migrated(self):
        app = self._create_app(self.source1, self.target1)
        mig = MigrateAddon(app)
        self.assertTrue(mig._check_addon_already_migrated())
        # Not installable on the target branch: not considered as migrated
        repo = self._git_repo(self.repo_path)
        target1 = extract_ref_info(repo, "target", self.target1)
        self._set_addon_not_installable(self.repo_upstream_path, target1.branch)
        app = self._create_app(self.source1, self.target1, fetch=True)
        mig = MigrateAddon(app)
        self.assertFalse(mig._check_addon_already_migrated())

    def test_migrate_not_installable_addon(self):
        repo = self._git_repo(self.repo_path)
        target1 = extract_ref_info(repo, "target", self.target1)
        self._set_addon_not_installable(self.repo_upstream_path, target1.branch)
        app = self._create_app(
            self.source1,
            self.target1,
            fetch=True,
            cli=True,
            pre_commit=False,
            module_migration=False,
        )
        with patch("click.confirm", return_value=True):
            res, __ = app.run_migrate()
        self.assertTrue(res)
        mig_branch = f"{app.target_version}-mig-{self.addon}"
        self.assertIn(mig_branch, repo.heads)
        self.assertEqual(repo.active_branch.name, mig_branch)
        # The non-installable addon has been removed before replaying its history
        messages = [c.message.strip() for c in repo.iter_commits(mig_branch)]
        self.assertEqual(messages[0], f"[ADD] {self.addon}")
        self.assertTrue(
            messages[1].startswith(f"[REM] {self.addon}: remove non-installable")
        )
        # The migrated addon is installable again
        with open(self.repo_path / self.addon / "__manifest__.py") as manifest:
            self.assertIn('"installable": True', manifest.read())
