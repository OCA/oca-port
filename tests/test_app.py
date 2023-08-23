import json

import oca_port

from . import common


class TestApp(common.CommonCase):
    def _create_app(self, from_branch, to_branch, **kwargs):
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
        params.update(kwargs)
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

    def test_app_commit_to_port_non_interactive(self):
        app = self._create_app(
            self._settings["branch1"],
            self._settings["branch2"],
            non_interactive=True,
        )
        self._commit_change_on_branch(self._settings["branch1"])
        result = app.run()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)

    def test_app_module_to_migrate_non_interactive(self):
        app = self._create_app(
            self._settings["branch2"],
            self._settings["branch3"],
            non_interactive=True,
        )
        result = app.run()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)

    def test_app_wrong_output(self):
        with self.assertRaisesRegex(ValueError, "Supported outputs are"):
            self._create_app(
                self._settings["branch2"],
                self._settings["branch3"],
                output="wrong_format",
            )

    def test_app_commit_to_port_output_json(self):
        app = self._create_app(
            self._settings["branch1"],
            self._settings["branch2"],
            output="json",
        )
        commit_sha = self._commit_change_on_branch(self._settings["branch1"])
        output = app.run()
        self.assertTrue(output)
        self.assertIsInstance(output, str)
        output = json.loads(output)
        self.assertEqual(output["process"], "port_commits")
        # A commit could be ported and is put in a "fake PR" without number
        self.assertEqual(len(output["results"]), 1)
        self.assertDictEqual(
            output["results"][""],
            {
                "url": "",
                "author": "",
                "title": "",
                "merged_at": "",
                "missing_commits": [commit_sha],
            },
        )

    def test_app_module_to_migrate_output_json(self):
        app = self._create_app(
            self._settings["branch2"],
            self._settings["branch3"],
            output="json",
        )
        output = app.run()
        self.assertTrue(output)
        self.assertIsInstance(output, str)
        output = json.loads(output)
        self.assertEqual(output["process"], "migrate")
        self.assertEqual(output["results"], {})
