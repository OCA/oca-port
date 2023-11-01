# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
import os
import pathlib
from dataclasses import dataclass

import git

from . import utils
from .exceptions import ForkValueError, RemoteBranchValueError
from .migrate_addon import MigrateAddon
from .port_addon_pr import PortAddonPullRequest
from .utils.git import Branch
from .utils.github import GitHub
from .utils.misc import Output, bcolors as bc


@dataclass
class App(Output):
    """'oca-port' application centralizing settings and operations.

    Parameters:

        from_branch:
            the source branch (e.g. '15.0')
        to_branch:
            the source branch (e.g. '16.0')
        addon:
            the name of the module to process
        repo_path:
            local path to the Git repository
        fork:
            name of the Git remote used as fork
        repo_name:
            name of the repository on the upstream organization (e.g. 'server-tools')
        user_org:
            name of the user's GitHub organization where the fork is hosted
        from_org:
            name of the upstream GitHub organization (default = 'OCA')
        from_remote:
            name of the Git remote considered as the upstream (default = 'origin')
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

    from_branch: str
    to_branch: str
    addon: str
    repo_path: str
    fork: str = None
    repo_name: str = None
    user_org: str = None
    from_org: str = "OCA"
    from_remote: str = "origin"
    verbose: bool = False
    non_interactive: bool = False
    output: str = None
    fetch: bool = False
    no_cache: bool = False
    clear_cache: bool = False
    github_token: str = None
    cli: bool = False  # Not documented, should not be used outside of the CLI

    _available_outputs = ("json",)

    def __post_init__(self):
        # Handle with repo_path and repo_name
        if self.repo_path:
            self.repo_path = pathlib.Path(self.repo_path)
        else:
            raise ValueError("'repo_path' has to be set.")
        if not self.repo_name:
            self.repo_name = self.repo_path.name
        # Handle Git repository
        self.repo = git.Repo(self.repo_path)
        if self.repo.is_dirty(untracked_files=True):
            raise ValueError("changes not committed detected in this repository.")
        # Handle user's organization and fork
        if not self.user_org:
            # Assume that the fork remote has the same name than the user organization
            self.user_org = self.fork
        if self.fork:
            if self.fork not in self.repo.remotes:
                raise ForkValueError(self.repo_name, self.fork)
        # Transform branch strings to Branch objects
        try:
            self.from_branch = Branch(
                self.repo, self.from_branch, default_remote=self.from_remote
            )
            self.to_branch = Branch(
                self.repo, self.to_branch, default_remote=self.from_remote
            )
        except ValueError as exc:
            if exc.args[1] not in self.repo.remotes:
                raise RemoteBranchValueError(self.repo_name, exc.args[1]) from exc
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
        # GitHub API helper
        self.github = GitHub(self.github_token or os.environ.get("GITHUB_TOKEN"))
        # Initialize storage & cache
        self.storage = utils.storage.InputStorage(self.to_branch, self.addon)
        self.cache = utils.cache.UserCacheFactory(self).build()

    def fetch_branches(self):
        for branch in (self.from_branch, self.to_branch):
            if not branch.remote:
                continue
            remote_url = branch.repo.remotes[branch.remote].url
            if self.verbose:
                self._print(f"Fetch {bc.BOLD}{branch.ref()}{bc.END} from {remote_url}")
            branch.repo.remotes[branch.remote].fetch(branch.name)

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
