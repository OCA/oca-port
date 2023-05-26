import json

import oca_port

from . import common


class TestApp(common.CommonCase):
    def _create_app(self, from_branch, to_branch):
        params = {
            "from_branch": from_branch,
            "to_branch": to_branch,
            "addon": self._settings["addon"],
            "upstream_org": self._settings["upstream_org"],
            "upstream": self._settings["upstream"],
            "repo_path": self.repo_path,
            "repo_name": "test",
            "user_org": self._settings["user_org"],
            "no_cache": self._settings["no_cache"],
        }
        # NOTE: app will run in non-interactive mode
        return oca_port.App(**params)

    def test_app_nothing_to_port(self):
        app = self._create_app(self._settings["branch1"], self._settings["branch2"])
        try:
            app.run()
        except SystemExit as exc:
            # exit code 0 means nothing needs to be migrated/ported
            self.assertEqual(exc.args[0], 0)

    def test_app_commit_to_port(self):
        app = self._create_app(self._settings["branch1"], self._settings["branch2"])
        self._commit_change_on_branch(self._settings["branch1"])
        try:
            app.run()
        except SystemExit as exc:
            # exit code 110 means pull requests or commits could be ported
            self.assertEqual(exc.args[0], 110)

    def test_app_module_to_migrate(self):
        app = self._create_app(self._settings["branch2"], self._settings["branch3"])
        try:
            app.run()
        except SystemExit as exc:
            # exit code 100 means the module could be migrated
            self.assertEqual(exc.args[0], 100)
