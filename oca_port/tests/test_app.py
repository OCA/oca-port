import json

from oca_port.app import App

from . import common


class TestApp(common.CommonCase):
    def _create_app(self, from_branch, to_branch, **kwargs):
        params = {
            "from_branch": from_branch,
            "to_branch": to_branch,
            "addon": self._settings["addon"],
            "from_org": self._settings["from_org"],
            "from_remote": self._settings["from_remote"],
            "repo_path": self.repo_path,
            "repo_name": "test",
            "user_org": self._settings["user_org"],
            "no_cache": self._settings["no_cache"],
        }
        params.update(kwargs)
        return App(**params)

    def test_app_nothing_to_port(self):
        app = self._create_app(
            self._settings["remote_branch1"], self._settings["remote_branch2"]
        )
        try:
            app.run()
        except SystemExit as exc:
            # exit code 0 means nothing needs to be migrated/ported
            self.assertEqual(exc.args[0], 0)

    def test_app_commit_to_port(self):
        self._commit_change_on_branch(
            self.repo_upstream_path, self._settings["branch1"]
        )
        app = self._create_app(
            self._settings["remote_branch1"],
            self._settings["remote_branch2"],
            fetch=True,
        )
        try:
            app.run()
        except SystemExit as exc:
            # exit code 110 means pull requests or commits could be ported
            self.assertEqual(exc.args[0], 110)
        # The other way around, no commit to backport (no exception)
        # (with CLI, the returned exit code is then 0)
        app = self._create_app(
            self._settings["remote_branch2"], self._settings["remote_branch1"]
        )
        res = app.run()
        self.assertFalse(res)

    def test_app_module_to_migrate(self):
        app = self._create_app(
            self._settings["remote_branch2"], self._settings["remote_branch3"]
        )
        try:
            app.run()
        except SystemExit as exc:
            # exit code 100 means the module could be migrated
            self.assertEqual(exc.args[0], 100)
        # The other way around, nothing to migrate as the module doesn't exist
        # (with CLI, the returned exit code is then 1)
        app = self._create_app(
            self._settings["remote_branch3"], self._settings["remote_branch2"]
        )
        error_msg = "my_module does not exist on origin/17.0"
        with self.assertRaisesRegex(ValueError, error_msg):
            app.run()

    def test_app_commit_to_port_non_interactive(self):
        self._commit_change_on_branch(
            self.repo_upstream_path, self._settings["branch1"]
        )
        app = self._create_app(
            self._settings["remote_branch1"],
            self._settings["remote_branch2"],
            non_interactive=True,
            fetch=True,
        )
        result = app.run()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)
        # The other way around, no commit to backport
        app = self._create_app(
            self._settings["remote_branch2"],
            self._settings["remote_branch1"],
            non_interactive=True,
        )
        result = app.run()
        self.assertFalse(result)
        self.assertIsInstance(result, bool)

    def test_app_module_to_migrate_non_interactive(self):
        app = self._create_app(
            self._settings["remote_branch2"],
            self._settings["remote_branch3"],
            non_interactive=True,
        )
        result = app.run()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)
        # The other way around, nothing to migrate as the module doesn't exist
        app = self._create_app(
            self._settings["remote_branch3"],
            self._settings["remote_branch2"],
            non_interactive=True,
        )
        error_msg = "my_module does not exist on origin/17.0"
        with self.assertRaisesRegex(ValueError, error_msg):
            app.run()

    def test_app_wrong_output(self):
        with self.assertRaisesRegex(ValueError, "Supported outputs are"):
            self._create_app(
                self._settings["remote_branch2"],
                self._settings["remote_branch3"],
                output="wrong_format",
            )

    def test_app_commit_to_port_output_json(self):
        commit_sha = self._commit_change_on_branch(
            self.repo_upstream_path, self._settings["branch1"]
        )
        app = self._create_app(
            self._settings["remote_branch1"],
            self._settings["remote_branch2"],
            output="json",
            fetch=True,
        )
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
                "ref": "",
                "author": "",
                "title": "",
                "merged_at": "",
                "missing_commits": [commit_sha],
            },
        )
        # The other way around, no commit to backport
        app = self._create_app(
            self._settings["remote_branch2"],
            self._settings["remote_branch1"],
            output="json",
        )
        output = app.run()
        self.assertTrue(output)
        self.assertIsInstance(output, str)
        output = json.loads(output)
        self.assertEqual(output, {})

    def test_app_module_to_migrate_output_json(self):
        app = self._create_app(
            self._settings["remote_branch2"],
            self._settings["remote_branch3"],
            output="json",
        )
        output = app.run()
        self.assertTrue(output)
        self.assertIsInstance(output, str)
        output = json.loads(output)
        self.assertEqual(output["process"], "migrate")
        self.assertEqual(output["results"], {})
        # The other way around, nothing to migrate as the module doesn't exist
        app = self._create_app(
            self._settings["remote_branch3"],
            self._settings["remote_branch2"],
            output="json",
        )
        error_msg = "my_module does not exist on origin/17.0"
        with self.assertRaisesRegex(ValueError, error_msg):
            app.run()
