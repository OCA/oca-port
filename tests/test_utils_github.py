# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest

from oca_port.utils import github


class TestGitHub(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.gh = github.GitHub(token="test")

    def test_token(self):
        assert self.gh.token == "test"

    def test_addon_in_text(self):
        # Matching OK
        res = self.gh._addon_in_text("a_b", "[16.0][MIG] a_b: migration to 16.0")
        assert res
        # Module name is not the expected one: do not match
        res = self.gh._addon_in_text("a_b", "[16.0][MIG] a_b_c: migration to 16.0")
        assert not res
