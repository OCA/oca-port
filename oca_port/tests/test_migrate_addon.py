from oca_port.migrate_addon import MigrateAddon

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
