# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
import os
import pathlib
from dataclasses import dataclass
import re

import git

from . import utils
from .exceptions import RemoteBranchValueError
from .migrate_addon import MigrateAddon
from .port_addon_pr import PortAddonPullRequest
from .utils.git import Branch
from .utils.github import GitHub
from .utils.misc import Output, bcolors as bc, extract_ref_info


@dataclass
class App(Output):
    """'oca-port' application centralizing settings and operations.

    Parameters:

        source:
            string representation of the source branch, e.g. 'origin/15.0'
        target:
            string representation of the target branch, e.g. 'origin/16.0'
        addon:
            the name of the module to process
        destination:
            string representation of the destination branch,
            e.g. 'camptocamp/16.0-addon-dev'
        source_version:
            Source Odoo version. To set if it cannot be detected from 'source'.
        target_version:
            Target Odoo version. To set if it cannot be detected from 'target'.
        repo_path:
            local path to the Git repository
        repo_name:
            name of the repository on the upstream organization (e.g. 'server-tools')
        verbose:
            returns more details to the user
        non_interactive:
            flag to not wait for user input and to return a error code to the shell.
            Returns 100 if an addon could be migrated, 110 if pull requests/commits
            could be ported, 0 if the history of the addon is the same on both branches.
        output:
            returns a parsable output. This implies the 'non-interactive' mode
            defined above but without returning any special exit code.
            Possible values: 'json'
        fetch:
            always fetch source and target branches from upstream
        no_cache:
            flag to disable the user's cache
        clear_cache:
            flag to remove the user's cache once the process is done
        github_token:
            Token to use when requesting GitHub API (highly recommended
            to not trigger the "API rate limit exceeded" error).
    """

    source: str
    target: str
    addon: str
    destination: str = None
    source_version: str = None
    target_version: str = None
    repo_path: str = ""
    repo_name: str = None
    upstream_org: str = "OCA"
    verbose: bool = False
    non_interactive: bool = False
    dry_run: bool = False
    output: str = None
    fetch: bool = False
    no_cache: bool = False
    clear_cache: bool = False
    github_token: str = None
    cli: bool = False  # Not documented, should not be used outside of the CLI

    _available_outputs = ("json",)

    def __post_init__(self):
        self._prepare_parameters()
        # Force non-interactive mode:
        #   - if we are not in CLI mode
        if not self.cli:
            self.non_interactive = True
        #   - if an output has been defined
        if self.output:
            if self.output.lower() not in self._available_outputs:
                outputs = ", ".join(self._available_outputs)
                raise ValueError(f"Supported outputs are: {outputs}")
            self.non_interactive = True
        # Fetch branches if they can't be resolved locally
        # NOTE: required for the storage below to retrieve data
        remote_branches = self.repo.git.branch("-r").split()
        if (
            self.fetch
            or (
                self.from_branch.remote
                and self.from_branch.ref() not in remote_branches
            )
            or (self.to_branch.remote and self.to_branch.ref() not in remote_branches)
        ):
            self.fetch_branches()
        # Check if source & target branches exist
        self._check_branch_exists(self.source.ref, raise_exc=True)
        self._check_branch_exists(self.target.ref, raise_exc=True)
        # GitHub API helper
        self.github = GitHub(self.github_token or os.environ.get("GITHUB_TOKEN"))
        # Initialize storage & cache
        self.storage = utils.storage.InputStorage(self.to_branch, self.addon)
        self.cache = utils.cache.UserCacheFactory(self).build()

    def _handle_odoo_versions(self):
        odoo_version_pattern = r"^[0-9]+\.[0-9]$"
        source_version = re.search(odoo_version_pattern, self.source.branch)
        target_version = re.search(odoo_version_pattern, self.target.branch)
        source_param = "--source-version" if self.cli else "source_version"
        target_param = "--target-version" if self.cli else "target_version"
        # Check Odoo versions from branches
        if not source_version and not self.source_version:
            raise ValueError(
                f"Unable to identify Odoo source version from {self.source.branch}.\n"
                f"Use {source_param} parameter to identify Odoo source version."
            )
        if not target_version and not self.target_version:
            raise ValueError(
                f"Unable to identify Odoo target version from {self.target.branch}.\n"
                f"Use {target_param} parameter to identify target Odoo version."
            )
        # Check source_version and target_version parameters
        if self.source_version and not re.search(
            odoo_version_pattern, self.source_version
        ):
            raise ValueError(f"Unable to identify Odoo version from {source_param}.")
        if self.target_version and not re.search(
            odoo_version_pattern, self.target_version
        ):
            raise ValueError(f"Unable to identify Odoo version from {target_param}.")
        self.source_version = self.source_version or source_version.string
        self.target_version = self.target_version or target_version.string

    def _prepare_parameters(self):
        # Handle Git repository
        self.repo = git.Repo(self.repo_path)
        if self.repo.is_dirty(untracked_files=True):
            raise ValueError("changes not committed detected in this repository.")

        # Convert them to full remote info if needed
        for key in ("source", "target", "destination"):
            value = getattr(self, key)
            if value and isinstance(value, str):
                setattr(self, key, extract_ref_info(self.repo, key, value))
        # Check Odoo versions from source and target branches and parameters
        self._handle_odoo_versions()

        # Always provide a destination:
        if not self.destination:
            self.destination = extract_ref_info(self.repo, "destination", "")
            # Unset org that could have been taken from 'origin'.
            self.destination.org = None
            # If target.org is different than upstream_org, generate the
            # destination from target so we get the remote+org for free (if any)
            if self.target.org != self.upstream_org:
                self.destination = extract_ref_info(
                    self.repo, "destination", self.target.ref
                )
                # If destination is not a local one, or not an Odoo version,
                # it will be generated by the specific tool
                if (
                    self.destination.remote
                    or self.destination.branch == self.target_version
                ):
                    self.destination.branch = None

        # Handle with repo_path and repo_name
        self.repo_path = pathlib.Path(self.repo_path)
        self.repo_name = (
            self.repo_name
            or self.source.repo
            or self.target.repo
            or self.repo_path.absolute().name
        )
        if not self.repo_path:
            raise ValueError("'repo_path' has to be set.")

        # Transform branch strings to Branch objects
        self.from_branch = self._prepare_branch(self.source)
        self.to_branch = self._prepare_branch(self.target)
        self.dest_branch = self.to_branch
        if self.destination.branch:
            self.dest_branch = self._prepare_branch(self.destination)

    def _prepare_branch(self, info):
        try:
            return Branch(self.repo, info.branch, default_remote=info.remote)
        except ValueError as exc:
            remote = exc.args[1]
            if remote not in self.repo.remotes:
                raise RemoteBranchValueError(info) from exc

    def fetch_branches(self):
        for branch in (self.from_branch, self.to_branch):
            if not branch.remote:
                continue
            remote_url = branch.repo.remotes[branch.remote].url
            if self.verbose:
                self._print(f"Fetch {bc.BOLD}{branch.ref()}{bc.END} from {remote_url}")
            branch.repo.remotes[branch.remote].fetch(branch.name)

    def _check_branch_exists(self, branch, raise_exc=False):
        for ref in self.repo.refs:
            if branch == ref.name:
                return True
        if raise_exc:
            raise ValueError(f"Ref {branch} doesn't exist.")
        return False

    def _check_addon_exists(self, branch, raise_exc=False):
        repo = self.repo
        addon = self.addon
        branch_addons = [t.path for t in repo.commit(branch.ref()).tree.trees]
        if addon not in branch_addons:
            if not raise_exc:
                return False
            error = f"{addon} does not exist on {branch.ref()}"
            if self.cli:
                error = f"{bc.FAIL}{addon}{bc.ENDC} does not exist on {branch.ref()}"
            raise ValueError(error)
        return True

    def check_addon_exists_from_branch(self, raise_exc=False):
        """Check that `addon` exists on the source branch`."""
        return self._check_addon_exists(self.from_branch, raise_exc=raise_exc)

    def check_addon_exists_to_branch(self, raise_exc=False):
        """Check that `addon` exists on the target branch`."""
        return self._check_addon_exists(self.to_branch, raise_exc=raise_exc)

    def run(self):
        """Run 'oca-port' to migrate an addon or to port its pull requests."""
        self.check_addon_exists_from_branch(raise_exc=True)
        # Check if some PRs could be ported
        res, output = self.run_port()
        if not res:
            # If not, migrate the addon
            res, output = self.run_migrate()
        if self.cli and self.output:
            if not output:
                output = self._render_output(self.output, {})
            print(output)
        if self.clear_cache:
            self.cache.clear()
        if self.output:
            return output
        return res

    def run_port(self):
        """Port pull requests of an addon (if any)."""
        # Check if the addon (folder) exists on the target branch
        #   - if it already exists, check if some PRs could be ported
        return PortAddonPullRequest(self).run()

    def run_migrate(self):
        """Migrate an addon."""
        return MigrateAddon(self).run()
