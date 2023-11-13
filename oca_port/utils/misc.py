# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import json
import os
import re
from collections import defaultdict

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


# Copy-pasted from OCA/maintainer-tools
def get_manifest_path(addon_dir):
    for manifest_name in MANIFEST_NAMES:
        manifest_path = os.path.join(addon_dir, manifest_name)
        if os.path.isfile(manifest_path):
            return manifest_path


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[39m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ENDD = "\033[22m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


def clean_text(text):
    """Clean text by removing patterns like '13.0', '[13.0]' or '[IMP]'."""
    return re.sub(r"\[.*\]|\d+\.\d+", "", text).strip()


def defaultdict_from_dict(d):
    nd = lambda: defaultdict(nd)  # noqa
    ni = nd()
    ni.update(d)
    return ni


class Output:
    """Mixin to handle the output of oca-port."""

    def _print(self, *args, **kwargs):
        """Like built-in 'print' method but check if oca-port is used in CLI."""
        app = self
        # FIXME: determine class
        if hasattr(self, "app"):
            app = self.app
        if app.cli and not app.output:
            print(*args, **kwargs)

    def _render_output(self, output, data):
        """Render the data with the expected format."""
        return getattr(self, f"_render_output_{output}")(data)

    def _render_output_json(self, data):
        """Render the data as JSON."""
        return json.dumps(data)


class SmartDict(dict):
    """Dotted notation dict."""

    def __getattr__(self, attrib):
        val = self.get(attrib)
        return self.__class__(val) if isinstance(val, dict) else val


REF_REGEX = r"((?P<org>[\w-]+)/)?((?P<repo>[\w-]+)#)?(?P<branch>.*)"


def parse_gh_ref(ref):
    """Parse github reference in the form [org/][repo#]branch"""
    group = re.match(REF_REGEX, ref)
    return SmartDict(group.groupdict()) if group else None


def make_gh_info(kind, ref, remote=None):
    info = parse_gh_ref(ref)
    if not info:
        # FIXME
        raise ValueError(f"No valid {kind}")
    info["_kind"] = kind
    info["remote"] = remote or info.org
    if not info.org:
        info["org"] = "OCA"
    return info


def pr_ref_from_url(url):
    if not url:
        return ""
    # url like 'https://github.com/OCA/edi/pull/371'
    org, repo, __, nr = url.split("/")[3:]
    return f"{org}/{repo}#{nr}"
