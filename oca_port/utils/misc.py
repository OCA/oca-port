# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import giturlparse
import json
import logging
import os
import re
import subprocess
from collections import defaultdict

_logger = logging.getLogger(__name__)

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


REF_REGEX = r"((?P<remote>[\w-]+)/)?(?P<branch>.*)"


def parse_ref(ref):
    """Parse reference in the form '[remote/]branch'."""
    group = re.match(REF_REGEX, ref)
    return SmartDict(group.groupdict()) if group else None


def extract_ref_info(repo, kind, ref, remote=None):
    """Extract info from `ref`.

    >>> extract_ref_info(repo, "source", "origin/16.0")
    {'remote': 'origin', 'repo': 'server-tools', 'platform': 'github', 'branch': '16.0', 'kind': 'src', 'org': 'OCA'}
    """
    info = parse_ref(ref)
    if not info:
        raise ValueError(f"No valid {kind}")
    info["ref"] = ref
    info["kind"] = kind
    info["remote"] = info["remote"] or remote
    info.update({"org": None, "platform": None})
    if info["remote"]:
        remote_url = repo.remotes[info["remote"]].url
        p = giturlparse.parse(remote_url)
        try:
            info["repo"] = p.repo
        except AttributeError:
            pass
        info["platform"] = p.platform
        info["org"] = p.owner
    else:
        # Fallback on 'origin' to grab info like platform, and repository name
        if "origin" in repo.remotes:
            remote_url = repo.remotes["origin"].url
            p = giturlparse.parse(remote_url)
            try:
                info["repo"] = p.repo
            except AttributeError:
                pass
            info["platform"] = p.platform
            info["org"] = p.owner
    return info


def pr_ref_from_url(url):
    if not url:
        return ""
    # url like 'https://github.com/OCA/edi/pull/371'
    org, repo, __, nr = url.split("/")[3:]
    return f"{org}/{repo}#{nr}"


def update_terms_in_directory(dir_path, old_term, new_term):
    """Update all `old_term` terms to `new_term` in `dir_path` directory."""
    # NOTE: requires 'find' and 'sed' tools available
    cmd = [
        "find",
        str(dir_path),
        "-type f",
        "! -name __init__.py",
        "-exec",
        f"sed -i 's/{old_term}/{new_term}/g'" + " {} \;",
    ]
    try:
        subprocess.check_call(" ".join(cmd), shell=True)
    except subprocess.CalledProcessError:
        _logger.warning(
            f"⚠️  Unable to rename '{old_term}' terms to '{new_term}' in {dir_path} directory"
        )
