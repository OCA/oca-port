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
    $ oca-port origin/13.0 origin/14.0 shopfloor --verbose

To effectively migrate the addon or port its commits, use the `--destination` option:

    $ oca-port origin/13.0 origin/14.0 shopfloor --destination camptocamp/14-mig-shopfloor

Note that you can omit the remote to work on local branches if needed:

    $ oca-port 13.0 camptocamp/14-dev shopfloor

NOTE: if the source branch is a local one, cache will be readonly and
won't be updated as commits data coming from such branch cannot be trust.

The organization used to perform API requests to look for Pull Requests data
is the one defined through `--upstream-org` parameter (defaults to 'OCA').
So you can work on local source and target branches while performing API requests
on the relevant upstream organization:

    $ oca-port 14.0 16.0 shopfloor --upstream-org camptocamp

To move/rename a module during its migration (or compare commits of a moved/renamed module):

    $ oca-port origin/16.0 origin/18.0 stock_packaging_calculator --move-to product_packaging_calculator

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

import click

from ..app import App
from ..exceptions import ForkValueError, RemoteBranchValueError
from ..utils.misc import bcolors as bc


@click.command()
@click.argument("source", required=True)
@click.argument("target", required=True)
@click.argument("addon_path", required=True)
@click.option(
    "--move-to",
    "target_addon_path",
    help=(
        "Expected name/path of the module on 'target'. "
        "Used to move or rename a module during a migration."
    ),
)
@click.option(
    "--destination",
    help=("Git reference where work will be pushed, e.g. 'camptocamp/16.0-dev'."),
)
@click.option(
    "--source-version",
    help="Source Odoo version. To set if it cannot be detected from 'source'.",
)
@click.option(
    "--target-version",
    help="Target Odoo version. To set if it cannot be detected from 'target'.",
)
@click.option("--repo-name", help="Repository name, e.g. 'server-tools'.")
@click.option(
    "--upstream-org",
    default="OCA",
    show_default=True,
    help="Upstream organization name. Used for API requests.",
)
@click.option("--verbose", is_flag=True, help="List the commits of Pull Requests.")
@click.option(
    "--non-interactive", is_flag=True, help="Disable all interactive prompts."
)
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Assume yes to prompts.")
@click.option("--dry-run", is_flag=True, help="Print results, no nothing.")
@click.option(
    "--output",
    help=(
        "Returns the result in a given format. "
        "This implies the `--non-interactive` option automatically. "
        "Possibles values are: 'json'."
    ),
)
@click.option("--fetch", is_flag=True, help="Fetch remote branches from upstream.")
@click.option(
    "--pre-commit/--no-pre-commit",
    default=True,
    help="Run pre-commit hooks after porting.",
)
@click.option(
    "--module-migration/--no-module-migration",
    default=True,
    help="Run odoo-module-migrator after porting.",
)
@click.option("--no-cache", is_flag=True, help="Disable user's cache.")
@click.option("--clear-cache", is_flag=True, help="Clear the user's cache.")
@click.option(
    "--github-token",
    is_flag=True,
    help="""Token to use when requesting GitHub API (highly recommended
            to not trigger the "API rate limit exceeded" error).""",
)
def main(
    addon_path: str,
    target_addon_path: str,
    source: str,
    target: str,
    destination: str,
    source_version: str,
    target_version: str,
    repo_name: str,
    upstream_org: str,
    verbose: bool,
    non_interactive: bool,
    assume_yes: bool,
    output: str,
    fetch: bool,
    pre_commit: bool,
    module_migration: bool,
    no_cache: bool,
    clear_cache: bool,
    dry_run: bool,
    github_token: str,
):
    """Migrate ADDON from SOURCE to TARGET or list Pull Requests to port.

        E.g.:

        $ oca-port origin/14.0 origin/16.0 auditlog

        Migration:

            Assist the user in the migration of the addon, following the OCA guidelines.

        Port of Pull Requests (missing commits):

            The PRs are found from SOURCE commits that do not exist in TARGET.
    The user will be asked if he wants to port them.
    """
    try:
        app = App(
            addon_path=addon_path,
            target_addon_path=target_addon_path,
            source=source,
            target=target,
            destination=destination,
            source_version=source_version,
            target_version=target_version,
            repo_name=repo_name,
            upstream_org=upstream_org,
            verbose=verbose,
            non_interactive=non_interactive,
            assume_yes=assume_yes,
            output=output,
            fetch=fetch,
            pre_commit=pre_commit,
            module_migration=module_migration,
            no_cache=no_cache,
            clear_cache=clear_cache,
            dry_run=dry_run,
            cli=True,
            github_token=github_token,
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
    except ValueError as exc:
        raise click.ClickException(exc) from exc
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
