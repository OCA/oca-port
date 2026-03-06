# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import os
import git_filter_repo as gfr
import tempfile
import urllib.parse
from importlib import metadata

import click

from .port_addon_pr import PortAddonPullRequest
from .utils import git as g
from .utils.misc import Output, bcolors as bc, update_terms_in_directory

MIG_BRANCH_NAME = "{branch}-mig-{addon}"
MIG_MERGE_COMMITS_URL = (
    "https://github.com/OCA/maintainer-tools/wiki/Merge-commits-in-pull-requests"
)
MIG_TASKS_URL = (
    "https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-{version}"
    "#tasks-to-do-in-the-migration"
)
MIG_NEW_PR_TITLE = "[{version}][MIG] {addon}"
MIG_NEW_PR_URL = (
    "https://github.com/{from_org}/{repo_name}/compare/"
    "{to_branch}...{to_org}:{mig_branch}?expand=1&title={title}"
)
MIG_STEPS = {
    "reduce_commits": (
        "Reduce the number of commits "
        f"('{bc.DIM}OCA Transbot...{bc.END}'):\n"
        f"\t\t=> {bc.BOLD}{MIG_MERGE_COMMITS_URL}{bc.END}"
    ),
    "adapt_module": (
        "Adapt the module to the {version} version:\n"
        f"\t\t=> {bc.BOLD}"
        "{mig_tasks_url}"
        f"{bc.END}"
    ),
    "amend_mig_commit": (
        "Include your changes in the existing migration commit:\n"
        f"{bc.DIM}"
        "\t\t$ git add --all\n"
        "\t\t$ git commit --amend\n"
        "\t\t$ git push {remote} {mig_branch} --set-upstream"
        f"{bc.END}"
    ),
    "commands": (
        "On a shell command, type this for uploading the content to GitHub:\n"
        f"{bc.DIM}"
        "\t\t$ git add --all\n"
        '\t\t$ git commit -m "[MIG] {addon}: Migration to {version}"\n'
        "\t\t$ git push {remote} {mig_branch} --set-upstream"
        f"{bc.END}"
    ),
    "create_pr": (
        "Create the PR against {from_org}/{repo_name}:\n"
        f"\t\t=> {bc.BOLD}"
        "{new_pr_url}"
        f"{bc.END}"
    ),
    "push_blacklist": (
        "On a shell command, type this for uploading the content to GitHub:\n"
        f"{bc.DIM}"
        "\t\t$ git push {remote} {mig_branch} --set-upstream"
        f"{bc.END}"
    ),
}
MIG_USUAL_STEPS = ("reduce_commits", "adapt_module", "commands", "create_pr")
MIG_BLACKLIST_STEPS = ("push_blacklist", "create_pr")
MIG_ADAPTED_STEPS = ("reduce_commits", "adapt_module", "amend_mig_commit", "create_pr")


class MigrateAddon(Output):
    def __init__(self, app):
        self.app = app
        self._results = {"process": "migrate", "results": {}}
        self.mig_branch = g.Branch(
            self.app.repo,
            (
                self.app.destination.branch
                or MIG_BRANCH_NAME.format(
                    branch=self.app.target_version, addon=self.app.source.addon
                )
            ),
        )

    def run(self):
        migrated = self._check_addon_already_migrated()
        blacklisted = self._check_addon_blacklisted()
        if migrated or blacklisted:
            if self.app.non_interactive or self.app.dry_run:
                if self.app.output:
                    return False, self._render_output(self.app.output, self._results)
            return False, None
        # At this stage, the addon could be migrated
        self._detect_existing_pr()
        if self.app.non_interactive or self.app.dry_run:
            msg = (
                f"ℹ️  {bc.BOLD}{self.app.source.addon}{bc.END} can be migrated "
                f"from {bc.BOLD}{self.app.source_version}{bc.END} "
                f"to {bc.BOLD}{self.app.target_version}{bc.END}"
            )
            if self.app.source.addon_path != self.app.target.addon_path:
                msg += f" and moved to {bc.BOLD}{self.app.target.addon_path}{bc.END}"
            else:
                msg += "."
            self._print(msg)
            # If an output is defined we return the result in the expected format
            if self.app.output:
                return True, self._render_output(self.app.output, self._results)
            if self.app.cli:
                # Exit with an error code if the addon is eligible for a migration
                # User-defined exit codes should be defined between 64 and 113.
                # Allocate 110 for 'PortAddonPullRequest'.
                raise SystemExit(100)
            return True, None
        if self.app.repo.is_dirty():
            # Same error message than git
            raise ValueError("You have unstaged changes. Please commit or stash them.")
        # Start the migration
        self._checkout_base_branch()
        if self.app.target.addon_path.exists():
            # Corner case: target addon already exists as local folder, abort
            self._print(
                f"{bc.BOLD}{self.app.target.addon}{bc.END} local directory "
                "(uncommitted) already exists, aborting."
            )
            return False, None
        confirm = (
            f"Migrate {bc.BOLD}{self.app.source.addon}{bc.END} "
            f"from {bc.BOLD}{self.app.source_version}{bc.END} "
            f"to {bc.BOLD}{self.app.target_version}{bc.END}"
        )
        if self.app.source.addon_path != self.app.target.addon_path:
            confirm += f" and move it to {bc.BOLD}{self.app.target.addon_path}{bc.END}?"
        else:
            confirm += "?"
        if not click.confirm(confirm):
            self.app.storage.blacklist_addon(confirm=True)
            if not self.app.storage.dirty:
                return False, None
        adapted = False
        if self._create_mig_branch():
            # Case where the addon shouldn't be ported (blacklisted)
            if self.app.storage.dirty:
                self.app.storage.commit()
                self._print_tips(blacklisted=True)
                return False, None
            # Port git history
            with tempfile.TemporaryDirectory() as patches_dir:
                self._generate_patches(patches_dir)
                self._apply_patches(patches_dir)
            # Handle module move/renaming
            if self.app.source.addon_path != self.app.target.addon_path:
                self._move_addon()
            # Run pre-commit
            if self.app.pre_commit:
                updated_files = g.run_pre_commit(self.app.repo)
                if updated_files:
                    g.commit(
                        self.app.repo,
                        msg=f"[IMP] {self.app.target.addon}: pre-commit auto fixes",
                        paths=updated_files,
                    )
            # Adapt code thanks to odoo-module-migrator (if installed)
            if self.app.module_migration:
                try:
                    metadata.metadata("odoo-module-migrator")
                    adapted = self._apply_code_pattern()
                except metadata.PackageNotFoundError:
                    pass
        # Check if the addon has commits that update neighboring addons to
        # make it work properly
        PortAddonPullRequest(self.app, push_branch=False).run()
        self._print_tips(adapted=adapted)
        return True, None

    def _check_addon_already_migrated(self):
        # if local:
        #     # Check if addon exists as a local folder
        #     # FIXME: this check should occurs once repo is checkout on target branch
        #     source_addon_exists = self.app.source.addon_path.exists()
        #     target_addon_exists = self.app.target.addon_path.exists()
        #     if source_addon_exists or target_addon_exists:
        #         addon = (
        #             self.app.source.addon
        #             if source_addon_exists
        #             else self.app.target.addon
        #         )
        #         self._print(
        #             f"{bc.BOLD}{addon}{bc.END} local directory (uncommitted) "
        #             "already exists, aborting."
        #         )
        #         return False
        # Check if addon exists in git trees (=> already migrated)
        source_addon_exists = self.app._check_addon_exists(
            self.app.source, self.app.to_branch
        )
        target_addon_exists = self.app._check_addon_exists(
            self.app.target, self.app.to_branch
        )
        if source_addon_exists or target_addon_exists:
            addon = (
                self.app.source.addon if source_addon_exists else self.app.target.addon
            )
            self._results = {}  # Nothing to report
            self._print(
                f"{bc.BOLD}{addon}{bc.END} is already migrated "
                f"on {bc.BOLD}{self.app.to_branch.ref()}{bc.END}, "
                "aborting."
            )
            return True
        return False

    def _check_addon_blacklisted(self):
        blacklisted = self.app.storage.is_addon_blacklisted()
        if blacklisted:
            self._results["results"]["blacklisted"] = True
            self._print(
                f"{bc.DIM}Migration of {bc.BOLD}{self.app.source.addon}{bc.END} "
                f"{bc.DIM}to {self.app.to_branch.name} "
                f"blacklisted ({blacklisted}){bc.ENDD}"
            )
        return blacklisted

    def _detect_existing_pr(self):
        """Looking for an existing PR to review."""
        existing_pr = None
        platform = self.app.target.platform

        if platform not in ("github",):
            return existing_pr

        if self.app.upstream_org and self.app.repo_name:
            existing_pr = self.app.github.search_migration_pr(
                from_org=self.app.upstream_org,
                repo_name=self.app.repo_name,
                branch=self.app.target.branch,
                addon=self.app.source.addon,
            )
        if existing_pr:
            self._print(
                f"⚠️\tMigration of {bc.BOLD}{self.app.source.addon}{bc.END} "
                f"seems handled in this PR:\n"
                f"\t\t{bc.BOLD}{existing_pr.url}{bc.END} (by {existing_pr.author})\n"
                "\tWe invite you to review this PR instead of opening a new one. "
                "Thank you!"
            )
            self._results["results"]["existing_pr"] = existing_pr.to_dict(number=True)

    def _checkout_base_branch(self):
        # Ensure to not start to work from a working branch
        if self.app.to_branch.name in self.app.repo.heads:
            self.app.repo.heads[self.app.to_branch.name].checkout(
                "--recurse-submodules",
            )
        else:
            self.app.repo.git.checkout(
                "--no-track",
                "--recurse-submodules",
                "-b",
                self.app.to_branch.name,
                self.app.to_branch.ref(),
            )

    def _create_mig_branch(self):
        create_branch = True
        if self.mig_branch.name in self.app.repo.heads:
            confirm = (
                f"Branch {bc.BOLD}{self.mig_branch.name}{bc.END} already exists, "
                "recreate it?\n(⚠️  you will lose the existing branch)"
            )
            if click.confirm(confirm):
                self.app.repo.delete_head(self.mig_branch.name, "-f")
            else:
                create_branch = False
        if create_branch:
            # Create branch
            print(
                f"\tCreate branch {bc.BOLD}{self.mig_branch.name}{bc.END} "
                f"from {self.app.to_branch.ref()}..."
            )
            self.app.repo.git.checkout(
                "--no-track",
                "--recurse-submodules",
                "-b",
                self.mig_branch.name,
                self.app.to_branch.ref(),
            )
        return create_branch

    def _generate_patches(self, patches_dir):
        print("\tGenerate patches...")
        self.app.repo.git.format_patch(
            "--keep-subject",
            "-o",
            patches_dir,
            f"{self.app.to_branch.ref()}..{self.app.from_branch.ref()}",
            "--",
            self.app.source.addon_path,
        )

    def _apply_patches(self, patches_dir):
        # FIXME: rework patches paths if module has been moved/renamed
        patches = [
            os.path.join(patches_dir, f) for f in sorted(os.listdir(patches_dir))
        ]
        # Apply patches with git-am
        print(f"\tApply {len(patches)} patches...")
        self.app.repo.git.am("-3", "--keep", *patches)
        print(
            f"\t\tCommits history of {bc.BOLD}{self.app.source.addon}{bc.END} "
            f"has been migrated."
        )

    def _move_addon(self):
        print(
            f"\Move module {bc.BOLD}{self.app.source.addon_path}{bc.END} "
            f"to {bc.BOLD}{self.app.target.addon_path}{bc.END}..."
        )
        path_rename = f"{self.app.source.addon_path}:{self.app.target.addon_path}"
        # Limit the rewriting of git history on current branch
        refs = f"{self.app.target.ref}..{self.mig_branch.name}"
        args = gfr.FilteringOptions.parse_args(
            [
                f"--path-rename={path_rename}",
                "--refs",
                refs,
                "--force",
            ]
        )
        filter_ = gfr.RepoFilter(args)
        filter_.run()
        if self.app.source.addon != self.app.target.addon:
            update_terms_in_directory(
                self.app.target.addon_path,
                self.app.source.addon,
                self.app.target.addon,
            )
        self.app.repo.git.add(self.app.target.addon_path)
        if self.app.repo.is_dirty():
            self.app.repo.git.commit(
                "-m",
                f"[MOV] Move {self.app.source.addon} to {self.app.target.addon}",
                "--no-verify",
            )

    def _print_tips(self, blacklisted=False, adapted=False):
        mig_tasks_url = MIG_TASKS_URL.format(version=self.app.target_version)
        pr_title_encoded = urllib.parse.quote(
            MIG_NEW_PR_TITLE.format(
                version=self.app.target_version, addon=self.app.source.addon
            )
        )
        new_pr_url = MIG_NEW_PR_URL.format(
            from_org=self.app.upstream_org,
            repo_name=self.app.repo_name,
            to_branch=self.app.to_branch.name,
            to_org=self.app.destination.org or "YOUR_ORG",
            mig_branch=self.mig_branch.name,
            title=pr_title_encoded,
        )
        if blacklisted:
            steps = self._generate_mig_steps(MIG_BLACKLIST_STEPS)
            tips = steps.format(
                from_org=self.app.upstream_org,
                repo_name=self.app.repo_name,
                remote=self.app.destination.remote,
                mig_branch=self.mig_branch.name,
                new_pr_url=new_pr_url,
            )
            print(tips)
            return tips
        if adapted:
            steps = self._generate_mig_steps(MIG_ADAPTED_STEPS)
            tips = steps.format(
                from_org=self.app.upstream_org,
                repo_name=self.app.repo_name,
                version=self.app.target_version,
                remote=self.app.destination.remote or "YOUR_REMOTE",
                mig_branch=self.mig_branch.name,
                mig_tasks_url=mig_tasks_url,
                new_pr_url=new_pr_url,
            )
            print(tips)
            return tips
        steps = self._generate_mig_steps(MIG_USUAL_STEPS)
        tips = steps.format(
            from_org=self.app.upstream_org,
            repo_name=self.app.repo_name,
            addon=self.app.source.addon,
            version=self.app.target_version,
            remote=self.app.destination.remote or "YOUR_REMOTE",
            mig_branch=self.mig_branch.name,
            mig_tasks_url=mig_tasks_url,
            new_pr_url=new_pr_url,
        )
        print(tips)
        return tips

    def _generate_mig_steps(self, steps):
        result = []
        for i, step in enumerate(steps, 1):
            text = f"\t{i}) " + MIG_STEPS[step]
            result.append(text)
        return "\n".join(result)

    def _apply_code_pattern(self):
        print("Apply code pattern...")
        from odoo_module_migrate.migration import Migration

        try:
            migration = Migration(
                self.app.target.addons_rootdir,
                self.app.source_version,
                self.app.target_version,
                module_names=[self.app.target.addon],
                pre_commit=False,
            )
            migration.run()
            return True
        except KeyboardInterrupt:
            pass
        return False
