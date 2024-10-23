# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from . import common

from oca_port.utils import session


class TestSession(common.CommonCase):
    def setUp(self):
        super().setUp()
        app = self._create_app(self.source1, self.target1, upstream_org="TEST")
        self.session_name = "test"
        self.session = session.Session(app, self.session_name)
        # Clear the session before each test
        self.session.clear()

    def tearDown(self):
        # Clear the session after each test
        self.session.clear()

    def test_session(self):
        key = "test"
        value = ["a", "b"]
        data = self.session.get_data()
        self.assertFalse(data)
        data[key] = value
        self.session.set_data(data)
        data2 = self.session.get_data()
        self.assertEqual(data2, data)
