# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
"""Tool helping to port an addon or missing commits of an addon from one branch
to another.

If the addon does not exist on the target branch, it will assist the user
in the migration, following the OCA migration guide.

If the addon already exists on the target branch, it will retrieve missing
commits to port. If a Pull Request exists for a missing commit, it will be
ported with all its commits if they were not yet (fully) ported.

To check if an addon could be migrated or to get eligible commits to port:

    $ export GITHUB_TOKEN=<token>
    $ oca-port 13.0 14.0 shopfloor --verbose

To effectively migrate the addon or port its commits, use the `--fork` option:

    $ oca-port 13.0 14.0 shopfloor --fork camptocamp


Migration of addon
------------------

The tool follows the usual OCA migration guide to port commits of an addon,
and will invite the user to fullfill the mentionned steps that can't be
performed automatically.

Port of commits/Pull Requests
-----------------------------

The tool will ask the user if he wants to open draft pull requests against
the upstream repository.

If there are several Pull Requests to port, it will ask the user if he wants to
base the next PR on the previous one, allowing the user to cumulate ported PRs
in one branch and creating a draft PR against the upstream repository with all
of them.
"""
import pathlib
import os
from dataclasses import dataclass

import click
import git

from . import utils
from .migrate_addon import MigrateAddon
from .port_addon_pr import PortAddonPullRequest
from .utils.misc import bcolors as bc
from .utils.git import Branch
from .exceptions import ForkValueError, RemoteBranchValueError


@click.command()
@click.argument("from_branch", required=True)
@click.argument("to_branch", required=True)
@click.argument("addon", required=True)
@click.option(
    "--upstream-org",
    default="OCA",
    show_default=True,
    help="Upstream organization name.",
)
@click.option(
    "--upstream",
    default="origin",
    show_default=True,
    required=True,
    help="Git remote from which source and target branches are fetched by default.",
)
@click.option("--repo-name", help="Repository name, eg. server-tools.")
@click.option(
    "--fork", help="Git remote where branches with ported commits are pushed."
)
@click.option("--user-org", show_default="--fork", help="User organization name.")
@click.option("--verbose", is_flag=True, help="List the commits of Pull Requests.")
@click.option(
    "--non-interactive", is_flag=True, help="Disable all interactive prompts."
)
@click.option("--no-cache", is_flag=True, help="Disable user's cache.")
@click.option("--clear-cache", is_flag=True, help="Clear the user's cache.")
def main(
    from_branch: str,
    to_branch: str,
    addon: str,
    upstream_org: str,
    upstream: str,
    repo_name: str,
    fork: str,
    user_org: str,
    verbose: bool,
    non_interactive: bool,
    no_cache: bool,
    clear_cache: bool,
):
    """Migrate ADDON from FROM_BRANCH to TO_BRANCH or list Pull Requests to port
        if ADDON already exists on TO_BRANCH.

        Migration:

            Assist the user in the migration of the addon, following the OCA guidelines.

        Port of Pull Requests (missing commits):

            The PRs are found from FROM_BRANCH commits that do not exist in TO_BRANCH.
    The user will be asked if he wants to port them.

        To start the migration process, the `--fork` option must be provided in
    order to push the resulting branch on the user's remote.
    """
    try:
        app = App(
            from_branch=from_branch,
            to_branch=to_branch,
            addon=addon,
            upstream_org=upstream_org,
            upstream=upstream,
            repo_path=os.getcwd(),
            repo_name=repo_name,
            fork=fork,
            user_org=user_org,
            verbose=verbose,
            non_interactive=non_interactive,
            no_cache=no_cache,
            clear_cache=clear_cache,
        )
    except ForkValueError as exc:
        error_msg = prepare_remote_error_msg(*exc.args)
        error_msg += (
            "\n\nYou can change the GitHub organization with the "
            f"{bc.DIM}--user-org{bc.END} option."
        )
        raise click.ClickException(error_msg) from exc
    except RemoteBranchValueError as exc:
        error_msg = prepare_remote_error_msg(*exc.args)
        raise click.ClickException(error_msg) from exc
    except ValueError:
        raise
    # Run the app
    try:
        app.run()
    except ValueError as exc:
        raise click.ClickException(exc) from exc


def prepare_remote_error_msg(repo_name, remote):
    return (
        f"No remote {bc.FAIL}{remote}{bc.END} in the current repository.\n"
        "To add it:\n"
        "\t# This mode requires an SSH key in the GitHub account\n"
        f"\t{bc.DIM}$ git remote add {remote} "
        f"git@github.com:{remote}/{repo_name}.git{bc.END}\n"
        "   Or:\n"
        "\t# This will require to enter user/password each time\n"
        f"\t{bc.DIM}$ git remote add {remote} "
        f"https://github.com/{remote}/{repo_name}.git{bc.END}"
    )


if __name__ == "__main__":
    main()


@dataclass
class App:
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
        upstream_org:
            name of the upstream GitHub organization (default = 'OCA')
        upstream:
            name of the Git remote considered as the upstream (default = 'origin')
        verbose:
            returns more details to the user
        non_interactive:
            flag to not wait for user input and to return a error code to the shell.
            Returns 1 if something can be ported, 0 otherwise.
        no_cache:
            flag to disable the user's cache
        clear_cache:
            flag to remove the user's cache once the process is done
    """

    from_branch: str
    to_branch: str
    addon: str
    repo_path: str
    fork: str = None
    repo_name: str = None
    user_org: str = None
    upstream_org: str = "OCA"
    upstream: str = "origin"
    verbose: bool = False
    non_interactive: bool = False
    no_cache: bool = False
    clear_cache: bool = False

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
                self.repo, self.from_branch, default_remote=self.upstream
            )
            self.to_branch = Branch(
                self.repo, self.to_branch, default_remote=self.upstream
            )
        except ValueError as exc:
            if exc.args[1] not in self.repo.remotes:
                raise RemoteBranchValueError(self.repo_name, exc.args[1]) from exc
        # Fetch branches if they can't be resolved locally
        # NOTE: required for the storage below to retrieve data
        remote_branches = self.repo.git.branch("-r").split()
        if (
            self.from_branch.remote and self.from_branch.ref() not in remote_branches
        ) or (self.to_branch.remote and self.to_branch.ref() not in remote_branches):
            self.fetch_branches()
        # Initialize storage & cache
        self.storage = utils.storage.InputStorage(self.to_branch, self.addon)
        self.cache = utils.cache.UserCacheFactory(self).build()

    def fetch_branches(self):
        for branch in (self.from_branch, self.to_branch):
            if not branch.remote:
                continue
            remote_url = branch.repo.remotes[branch.remote].url
            if self.verbose:
                print(f"Fetch {bc.BOLD}{branch.ref()}{bc.END} from {remote_url}")
            branch.repo.remotes[branch.remote].fetch(branch.name)

    def _check_addon_exists(self, branch, raise_exc=False):
        repo = self.repo
        addon = self.addon
        branch_addons = [t.path for t in repo.commit(branch.ref()).tree.trees]
        if addon not in branch_addons:
            if not raise_exc:
                return False
            raise ValueError(
                f"{bc.FAIL}{addon}{bc.ENDC} does not exist on {branch.ref()}"
            )
        return True

    def check_addon_exists_from_branch(self, raise_exc=False):
        """Check that `addon` exists on the source branch`."""
        return self._check_addon_exists(self.from_branch, raise_exc=raise_exc)

    def check_addon_exists_to_branch(self, raise_exc=False):
        """Check that `addon` exists on the target branch`."""
        return self._check_addon_exists(self.to_branch, raise_exc=raise_exc)

    def run(self):
        """Run 'oca-port' to migrate an addon or to port its pull requests."""
        self.fetch_branches()
        self.check_addon_exists_from_branch(raise_exc=True)
        # Check if some PRs could be ported
        if not self.run_port():
            # If not, migrate the addon
            self.run_migrate()
        if self.clear_cache:
            self.cache.clear()

    def run_port(self):
        """Port pull requests of an addon (if any)."""
        # Check if the addon (folder) exists on the target branch
        #   - if it already exists, check if some PRs could be ported
        if self.check_addon_exists_to_branch():
            PortAddonPullRequest(self).run()
            return True
        return False

    def run_migrate(self):
        """Migrate an addon."""
        MigrateAddon(self).run()
        return True
