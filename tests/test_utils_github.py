# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from oca_port.utils import github


def test_addon_in_text():
    # Matching OK
    res = github._addon_in_text("a_b", "[16.0][MIG] a_b: migration to 16.0")
    assert res
    # Module name is not the expected one: do not match
    res = github._addon_in_text("a_b", "[16.0][MIG] a_b_c: migration to 16.0")
    assert not res
