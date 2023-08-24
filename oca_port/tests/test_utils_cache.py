# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from . import common

from oca_port.utils import cache


class TestUserCache(common.CommonCase):
    def setUp(self):
        super().setUp()
        app = self._create_app(self.source1, self.target1, upstream_org="TEST")
        self.cache = cache.UserCache(app)
        # As source branch as no organization, cache is by default readonly.
        # Unset this to run tests.
        self.cache.readonly = False
        # Clear the cache before each test
        self.cache.clear()

    def tearDown(self):
        # Clear the cache after each test
        self.cache.clear()

    def test_commit_ported(self):
        sha = "TEST"
        self.assertFalse(self.cache.is_commit_ported(sha))
        self.cache.mark_commit_as_ported(sha)
        self.assertTrue(self.cache.is_commit_ported(sha))

    def test_commit_pr(self):
        sha = "TEST"
        pr_data = {
            "number": 10,
            "title": "TEST",
        }
        self.assertFalse(self.cache.get_pr_from_commit(sha))
        self.cache.store_commit_pr(sha, pr_data)
        self.assertDictEqual(self.cache.get_pr_from_commit(sha), pr_data)

    def test_commit_files(self):
        sha = "TEST"
        files = ["a/b/test", "a/data"]
        self.assertFalse(self.cache.get_commit_files(sha))
        self.cache.set_commit_files(sha, files)
        self.assertEqual(self.cache.get_commit_files(sha), files)
