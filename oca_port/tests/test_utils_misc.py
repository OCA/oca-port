# Copyright 2023 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import io
import os
import pathlib
import sys
import tempfile
from collections import defaultdict
from contextlib import contextmanager

from oca_port.utils import misc


@contextmanager
def make_tmp_addon(name, manifest_name="__manifest__.py"):
    with tempfile.TemporaryDirectory() as path:
        os.system(f"mkdir -p {path}/addons/{name}")
        addons_path = f"{path}/addons"
        addon_path = f"{addons_path}/{name}"
        os.system(f"touch {addon_path}/{manifest_name}")
        yield pathlib.Path(addons_path)


@contextmanager
def capture_stdout():
    captured = io.StringIO()
    sys.stdout = captured
    yield captured
    sys.stdout = sys.__stdout__


def test_get_manifest_path():
    with make_tmp_addon("foo") as addons_path:
        expected = f"{addons_path}/foo/__manifest__.py"
        assert misc.get_manifest_path(addons_path / "foo") == expected


def test_clean_text():
    assert misc.clean_text("[13.0] foo 13.0") == "foo"


def test_default_dict_from_dict():
    res = misc.defaultdict_from_dict({"a": 1})
    # original values preserved
    assert res["a"] == 1
    # any key is a dict by default
    assert isinstance(res["b"], defaultdict)
    assert isinstance(res["b"]["c"], defaultdict)
    assert isinstance(res["b"]["c"]["d"], defaultdict)


def test_output_cli_mode():
    output = misc.Output()
    output.cli = True
    output.output = None
    with capture_stdout() as captured:
        output._print("foo")
        output._print("baz")
        output._print("bar")
        captured.seek(0)
        assert captured.read() == "foo\nbaz\nbar\n"

    assert output._render_output("json", {"a": 1}) == '{"a": 1}'
