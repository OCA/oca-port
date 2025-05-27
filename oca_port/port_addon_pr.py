# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import os
import hashlib
import itertools
import pathlib
import shutil
import tempfile
import urllib.parse
from collections import defaultdict

import click
import git
import requests

from .utils import git as g, misc
from .utils.session import Session
from .utils.misc import Output, bcolors as bc

AUTHOR_EMAILS_TO_SKIP = [
    "transbot@odoo-community.org",
    "noreply@weblate.org",
    "oca-git-bot@odoo-community.org",
    "oca+oca-travis@odoo-community.org",
    "oca-ci@odoo-community.org",
    "shopinvader-git-bot@shopinvader.com",
]

SUMMARY_TERMS_TO_SKIP = [
    "Translated using Weblate",
    "Added translation using Weblate",
]

PR_BRANCH_NAME = "oca-port-{addon}-{source_version}-to-{target_version}-{key}"

FOLDERS_TO_SKIP = [
    "setup",
    ".github",
]

FILES_TO_KEEP = [
    "requirements.txt",
    "test-requirements.txt",
    "oca_dependencies.txt",
]

BOT_FILES_TO_SKIP = [
    "README.rst",
    "static/description/index.html",
]

NEW_PR_URL = (
    "https://github.com/{from_org}/{repo_name}/compare/"
    "{to_branch}...{to_org}:{pr_branch}?expand=1&title={title}"
)


def path_to_skip(commit_path):
    """Return True if the commit path should not be ported."""
    # Allows all folders (addons!) excepted those like 'setup/' generated
    # automatically by pre-commit.
    if commit_path.isdir:
        return commit_path in FOLDERS_TO_SKIP
    # Forbid all files excepted those that developers could update
    return commit_path not in FILES_TO_KEEP


class PortAddonPullRequest(Output):
    def __init__(self, app, push_branch=True):
        """Port pull requests of an addon."""
        self.app = app
        self.push_branch = push_branch and bool(self.app.destination.remote)
        self.open_pr = bool(self.app.destination.org)
        self._results = {"process": "port_commits", "results": {}}

    def run(self):
        if not self.app.check_addon_exists_to_branch():
            if self.app.non_interactive:
                if self.app.output:
                    return False, self._render_output(self.app.output, {})
            return False, None
        self._print(
            f"{bc.BOLD}{self.app.addon}{bc.END} already exists "
            f"on {bc.BOLD}{self.app.to_branch.ref()}{bc.END}, "
            "checking PRs to port..."
        )
        branches_diff = BranchesDiff(self.app)
        if branches_diff.commits_diff["addon"]:
            branches_diff.print_diff(verbose=self.app.verbose)
        if branches_diff.commits_diff["satellite"]:
            branches_diff.print_satellite_diff(verbose=self.app.verbose)
        if self.app.non_interactive:
            if branches_diff.commits_diff["addon"]:
                # If an output is defined we return the result in the expected format
                if self.app.output:
                    self._results["results"] = branches_diff.serialized_diff
                    return True, self._render_output(self.app.output, self._results)
                if self.app.cli:
                    # Exit with an error code if commits are eligible for (back)porting
                    # User-defined exit codes should be defined between 64 and 113.
                    # Allocate 110 for 'PortAddonPullRequest'.
                    raise SystemExit(110)
                return True, None
            if self.app.output:
                # Nothing to port -> return an empty output
                return False, self._render_output(self.app.output, {})
            return False, None
        if not self.app.dry_run:
            self._print()
            # Set a destination branch (automatically generated if not already provided)
            self.app.destination.branch = self._get_dest_branch_name(branches_diff)
            # Launch the porting session
            porting_done = self._port_pull_requests(branches_diff)
            if porting_done:
                self._commit_blacklist()
                self._push_and_open_pr()
        return True, None

    def _get_dest_branch_name(self, branches_diff):
        dest_branch_name = self.app.destination.branch
        # Define a destination branch if not set
        if branches_diff.commits_diff["addon"] and not dest_branch_name:
            commits_to_port = [
                commit.hexsha
                for commit in itertools.chain.from_iterable(
                    branches_diff.commits_diff["addon"].values()
                )
            ]
            h = hashlib.shake_256("-".join(commits_to_port).encode())
            key = h.hexdigest(3)
            dest_branch_name = PR_BRANCH_NAME.format(
                addon=self.app.addon,
                source_version=self.app.source_version,
                target_version=self.app.target_version,
                key=key,
            )
        return dest_branch_name

    def _port_pull_requests(self, branches_diff):
        """Open new Pull Requests (if it doesn't exist) on the GitHub repository."""
        # Now we have a destination branch, check if there is ongoing work on it
        wip = self._print_wip_session()
        dest_branch_name = self.app.destination.branch
        # Nothing to port
        if not branches_diff.commits_diff["addon"] or not dest_branch_name:
            # Nothing to port while having WIP means the porting is done
            return wip
        # Check if destination branch exists, and create it if not
        dest_branch_exists = dest_branch_name in self.app.repo.heads
        base_ref = self.app.to_branch  # e.g. 'origin/14.0'
        if dest_branch_exists:
            target_commit = self.app.repo.commit(self.app.target.ref)
            dest_commit = self.app.repo.commit(dest_branch_name)
            # If target and destination branches are on the same commit we don't care
            if target_commit != dest_commit:
                # If the local branch already exists, ask the user if he wants
                # to recreate it
                confirm = (
                    f"Branch {bc.BOLD}{dest_branch_name}{bc.END} already exists, "
                    f"recreate it from {bc.BOLD}{self.app.to_branch.ref()}{bc.END}?\n"
                    "(⚠️  you will lose ongoing work)"
                )
                if not click.confirm(confirm):
                    msg = "ℹ️  To resume the work from this branch, relaunch with:\n\n"
                    cmd = (
                        f"\t{bc.DIM}oca-port {self.app.source.ref} "
                        f"{dest_branch_name} {self.app.addon_path} %s{bc.END}"
                    )
                    opts = []
                    if self.app.source.branch != self.app.source_version:
                        opts.append(f"--source-version={self.app.source_version}")
                    if dest_branch_name != self.app.target_version:
                        opts.append(f"--target-version={self.app.target_version}")
                    if self.app.verbose:
                        opts.append("--verbose")
                    cmd = cmd % " ".join(opts)
                    self._print(msg + cmd)
                    return False
                # Delete the local branch
                if self.app.repo.active_branch.name == dest_branch_name:
                    # We cannot delete an active branch, checkout the underlying
                    # commit instead
                    self.app.repo.git.checkout(dest_commit)
                self.app.repo.delete_head(dest_branch_name, "-f")
                dest_branch_exists = False
                # Clear any ongoing work from the session
                session = self._init_session()
                session.clear()
        if not dest_branch_exists:
            self.app.repo.git.checkout(
                "--no-track", "-b", dest_branch_name, base_ref.ref()
            )
        # Checkout the destination branch before porting PRs
        dest_branch = g.Branch(self.app.repo, dest_branch_name)
        self.app.repo.heads[dest_branch.name].checkout()
        last_pr = (
            list(branches_diff.commits_diff["addon"].keys())[-1]
            if branches_diff.commits_diff["addon"]
            else None
        )
        for pr, commits in branches_diff.commits_diff["addon"].items():
            # Check if PR has been blacklisted in user's session
            if self._is_pr_blacklisted(pr):
                if self._confirm_pr_blacklisted(pr):
                    continue
            # Port PR
            current_commit = self.app.repo.commit(dest_branch.ref())
            pr_ported = self._port_pull_request_commits(
                pr,
                commits,
                base_ref,
                dest_branch,
            )
            if pr_ported:
                # Check if commits have been ported.
                # If none has been ported, blacklist automatically the current PR.
                if self.app.repo.commit(dest_branch.ref()) == current_commit:
                    self._print("\tℹ️  Nothing has been ported, skipping")
                    self._handle_pr_blacklist(
                        pr, reason=f"(auto) Nothing to port from PR #{pr.number}"
                    )
                    msg = (
                        f"\t{bc.DIM}PR #{pr.number} has been"
                        if pr.number
                        else "Orphaned commits have been"
                    ) + f" automatically blacklisted{bc.ENDD}"
                    self._print(msg)
                    continue
                self._handle_pr_ported(pr)
                if pr == last_pr:
                    self._print("\t🎉 Last PR processed! 🎉")
        return True

    def _get_session_name(self):
        return f"{self.app.addon}-{self.app.destination.branch}"

    def _init_session(self):
        session = Session(self.app, self._get_session_name())
        data = session.get_data()
        data.setdefault("addon", self.app.addon)
        data.setdefault("repo_name", self.app.repo_name)
        data.setdefault("pull_requests", {})
        session.set_data(data)
        return session

    def _is_pr_blacklisted(self, pr):
        """Check if PR is blacklisted in current user's session."""
        session = self._init_session()
        data = session.get_data()
        return bool(data["pull_requests"]["blacklisted"][pr.ref])

    def _confirm_pr_blacklisted(self, pr):
        """Ask the user if PR should still be blacklisted."""
        self._print(
            f"- {bc.BOLD}{bc.WARNING}PR #{pr.number}{bc.END} "
            f"is blacklisted in current user's session"
        )
        if not click.confirm("\tKeep it blacklisted?"):
            # Remove the PR from the session
            session = self._init_session()
            data = session.get_data()
            if pr.ref in data["pull_requests"]["blacklisted"]:
                del data["pull_requests"]["blacklisted"][pr.ref]
            session.set_data(data)
            return False
        return True

    def _handle_pr_blacklisted(self, pr):
        """Check if PR is blacklisted in current user's session.

        Return True if workflow
        """

    def _handle_pr_blacklist(self, pr, reason=None):
        if not click.confirm("\tBlacklist this PR?"):
            return False
        if not reason:
            reason = click.prompt("\tReason", type=str)
        session = self._init_session()
        data = session.get_data()
        blacklisted = data["pull_requests"].setdefault("blacklisted", {})
        if pr.ref not in blacklisted:
            pr_data = pr.to_dict(number=True)
            pr_data["reason"] = reason
            data["pull_requests"]["blacklisted"][pr.ref] = pr_data
        session.set_data(data)
        return True

    def _handle_pr_ported(self, pr):
        session = self._init_session()
        data = session.get_data()
        ported = data["pull_requests"].setdefault("ported", {})
        if pr.ref not in ported:
            data["pull_requests"]["ported"][pr.ref] = pr.to_dict(number=True)
        session.set_data(data)

    def _commit_blacklist(self):
        session = self._init_session()
        data = session.get_data()
        blacklisted = data["pull_requests"].setdefault("blacklisted", {})
        for pr in blacklisted.values():
            if (
                self.app.storage.is_pr_blacklisted(pr["ref"])
                # TODO: Backward compat for old tracking only by number
                or self.app.storage.is_pr_blacklisted(pr["number"])
            ):
                continue
            self.app.storage.blacklist_pr(pr["ref"], reason=pr["reason"])
        if self.app.storage.dirty:
            pr_refs = ", ".join([str(pr["number"]) for pr in blacklisted.values()])
            self.app.storage.commit(
                msg=f"oca-port: blacklist PR(s) {pr_refs} for {self.app.addon}"
            )

    def _print_wip_session(self):
        session = self._init_session()
        data = session.get_data()
        wip = False
        if data["pull_requests"]:
            self._print(
                f"ℹ️  Existing session for branch "
                f"{bc.BOLD}{self.app.destination.branch}{bc.END}:"
            )
            wip = True
        # Ported PRs
        if data["pull_requests"]["ported"]:
            self._print("\t✅ Ported PRs:")
        for pr_data in data["pull_requests"]["ported"].values():
            self._print(
                f"\t- {bc.BOLD}{bc.OKBLUE}{pr_data['ref']}{bc.END} "
                f"{bc.OKBLUE}{pr_data['title']}{bc.ENDC}:"
            )
        # Blacklisted PRs
        if data["pull_requests"]["blacklisted"]:
            self._print("\t⛔ Blacklisted PRs:")
        for pr_data in data["pull_requests"]["blacklisted"].values():
            self._print(
                f"\t- {bc.BOLD}{bc.WARNING}{pr_data['ref']}{bc.END} "
                f"{bc.WARNING}{pr_data['title']}{bc.ENDC}:"
            )
        # if data["pull_requests"]:
        #     self._print()
        return wip

    def _push_and_open_pr(self):
        session = self._init_session()
        data = session.get_data()
        processed_prs = data["pull_requests"]["ported"]
        blacklisted_prs = data["pull_requests"]["blacklisted"]
        if not processed_prs and not blacklisted_prs:
            self._print("ℹ️  Nothing has been ported or blacklisted.")
            return False
        pr_data = self._prepare_pull_request_data(processed_prs, blacklisted_prs)
        # Try to push and open PR against remote repository
        is_pushed = self._push_branch_to_remote()
        if not is_pushed:
            self._print(
                f"\nℹ️  Branch {bc.BOLD}{self.app.destination.branch}{bc.END} couldn't "
                "be pushed (no remote defined)"
            )
            self._print_tips(pr_data)
            return False
        if not self.open_pr:
            self._print(
                f"\nℹ️  PR based on {bc.BOLD}{self.app.destination.branch}{bc.END} couldn't "
                "be open (no remote defined)"
            )
            self._print_tips(pr_data)
            return False
        pr_url = self._search_pull_request(pr_data["base"], pr_data["title"])
        if pr_url:
            self._print(f"Existing PR has been refreshed => {pr_url}")
        else:
            self._create_pull_request(pr_data, processed_prs)

    def _print_tips(self, pr_data):
        self._print("Here is the default PR content that would have been used:")
        self._print(f"\n{bc.BOLD}Title:{bc.END}")
        self._print(pr_data["title"])
        self._print(f"\n{bc.BOLD}Description:{bc.END}")
        self._print(pr_data["body"])

    def _port_pull_request_commits(self, pr, commits, base_ref, branch):
        """Port commits of a Pull Request in a new branch."""
        if pr.number:
            self._print(
                f"- {bc.BOLD}{bc.OKCYAN}Port PR {pr.ref}{bc.END} "
                f"{bc.OKCYAN}{pr.title}{bc.ENDC}..."
            )
            self._print(f"\t{pr.url}")
        else:
            self._print(f"- {bc.BOLD}{bc.OKCYAN}Port commits w/o PR{bc.END}...")
        # Ask the user if he wants to port the PR (or orphaned commits)
        if not click.confirm("\tPort it?" if pr.number else "\tPort them?"):
            self._handle_pr_blacklist(pr)
            return False

        # Cherry-pick commits of the source PR
        for commit in commits:
            self._print(
                f"\t\tApply {bc.OKCYAN}{commit.hexsha[:8]}{bc.ENDC} "
                f"{commit.summary}..."
            )
            # Port only relevant diffs/paths from the commit
            paths_to_port = set(commit.paths_to_port)
            for diff in commit.diffs:
                skip, message = self._skip_diff(commit, diff)
                if skip:
                    if message:
                        self._print(f"\t\t\t{message}")
                    if diff.a_path in paths_to_port:
                        paths_to_port.remove(diff.a_path)
                    if diff.b_path in paths_to_port:
                        paths_to_port.remove(diff.b_path)
                    continue
            if not paths_to_port:
                self._print("\t\t\tℹ️  Nothing to port from this commit, skipping")
                continue
            try:
                patches_dir = tempfile.mkdtemp()
                self.app.repo.git.format_patch(
                    "--keep-subject",
                    "-o",
                    patches_dir,
                    "-1",
                    commit.hexsha,
                    "--",
                    *paths_to_port,
                )
                patches = [
                    os.path.join(patches_dir, f)
                    for f in sorted(os.listdir(patches_dir))
                ]
                self.app.repo.git.am("-3", "--keep", *patches)
                shutil.rmtree(patches_dir)
            except git.exc.GitCommandError as exc:
                self._print(f"{bc.FAIL}ERROR:{bc.ENDC}\n{exc}\n")
                # High chance a conflict occurs, ask the user to resolve it
                if not click.confirm(
                    "⚠️  A conflict occurs, please resolve it and "
                    "confirm to continue the process (y) or skip this commit (N)."
                ):
                    self.app.repo.git.am("--abort")
                    continue
        return True

    @staticmethod
    def _skip_diff(commit, diff):
        """Check if a commit diff should be skipped or not.

        A skipped diff won't have its file path ported through 'git format-path'.

        Return a tuple `(bool, message)` if the diff is skipped.
        """
        if diff.deleted_file:
            if diff.a_path not in commit.paths_to_port:
                return True, ""
        if diff.b_path not in commit.paths_to_port:
            return True, ""
        if diff.renamed:
            return False, ""
        diff_path = diff.b_path.split("/", maxsplit=1)[0]
        # Skip diff updating auto-generated files (pre-commit, bot...)
        if any(file_path in diff_path for file_path in BOT_FILES_TO_SKIP):
            return (
                True,
                f"SKIP: '{diff.change_type} {diff.b_path}' diff relates "
                "to an auto-generated file, skip to avoid conflict",
            )
        # Do not accept diff on unported addons
        if (
            not misc.get_manifest_path(diff_path)
            and diff_path not in commit.addons_created
        ):
            return (
                True,
                (
                    f"{bc.WARNING}SKIP diff "
                    f"{bc.BOLD}{diff.change_type} {diff.b_path}{bc.END}: "
                    "relates to an unported addon"
                ),
            )
        if diff.change_type in ("M", "D"):
            # Do not accept update and deletion on non-existing files
            if not os.path.exists(diff.b_path):
                return (
                    True,
                    (
                        f"SKIP: '{diff.change_type} {diff.b_path}' diff relates "
                        "to a non-existing file"
                    ),
                )
        return False, ""

    def _push_branch_to_remote(self):
        """Force push the local branch to remote destination fork."""
        if not self.push_branch:
            return False
        confirm = (
            f"Push branch '{bc.BOLD}{self.app.destination.branch}{bc.END}' "
            f"to remote '{bc.BOLD}{self.app.destination.remote}{bc.END}'?"
        )
        if click.confirm(confirm):
            self.app.repo.git.push(
                self.app.destination.remote,
                self.app.destination.branch,
                "--force-with-lease",
            )
            return True
        return False

    def _prepare_pull_request_data(self, processed_prs, blacklisted_prs):
        # Adapt the content depending on the number of ported PRs
        title = body = ""
        if len(processed_prs) > 1:
            title = (
                f"[{self.app.target_version}][FW] {self.app.addon}: multiple ports "
                f"from {self.app.source_version}"
            )
        if len(processed_prs) == 1:
            pr = list(processed_prs.values())[0]
            title = f"[{self.app.target_version}][FW] {pr['title']}"
        if processed_prs:
            lines = [f"- #{pr['number']}" for pr in processed_prs.values()]
            body = "\n".join(
                [f"Port from {self.app.source_version} to {self.app.target_version}:"]
                + lines
            )
        # Handle blacklisted PRs
        if blacklisted_prs:
            if not title:
                title = (
                    f"[{self.app.target_version}][FW] Blacklist of some PRs "
                    f"from {self.app.source_version}"
                )
            lines2 = [
                f"- #{pr['number']}: {pr['reason']}" for pr in blacklisted_prs.values()
            ]
            body2 = "\n".join(["The following PRs have been blacklisted:"] + lines2)
            if body:
                body = "\n\n".join([body, body2])
            else:
                body = body2
        return {
            "draft": True,
            "title": title,
            "head": f"{self.app.destination.org}:{self.app.destination.branch}",
            "base": self.app.to_branch.name,
            "body": body,
        }

    def _search_pull_request(self, base_branch, title):
        params = {
            "q": (
                f"is:pr "
                f"repo:{self.app.upstream_org}/{self.app.repo_name} "
                f"base:{base_branch} "
                f"state:open {title} in:title"
            ),
        }
        response = self.app.github.request("search/issues", params=params)
        if response["items"]:
            return response["items"][0]["html_url"]

    def _create_pull_request(self, pr_data, processed_prs):
        if len(processed_prs) > 1:
            self._print(
                "PR(s) ported locally:",
                ", ".join(
                    [f"{bc.OKCYAN}#{pr.number}{bc.ENDC}" for pr in processed_prs]
                ),
            )
        if click.confirm(
            f"Create a draft PR from '{bc.BOLD}{self.app.destination.branch}{bc.END}' "
            f"to '{bc.BOLD}{self.app.to_branch.name}{bc.END}' "
            f"against {bc.BOLD}{self.app.upstream_org}/{self.app.repo_name}{bc.END}?"
        ):
            response = self.app.github.request(
                f"repos/{self.app.upstream_org}/{self.app.repo_name}/pulls",
                method="post",
                json=pr_data,
            )
            pr_url = response["html_url"]
            self._print(
                f"\t{bc.BOLD}{bc.OKCYAN}PR created =>" f"{bc.ENDC} {pr_url}{bc.END}"
            )
            return pr_url
        # Invite the user to open the PR on its own
        pr_title_encoded = urllib.parse.quote(pr_data["title"])
        new_pr_url = NEW_PR_URL.format(
            from_org=self.app.upstream_org,
            repo_name=self.app.repo_name,
            to_branch=self.app.to_branch.name,
            to_org=self.app.destination.org,
            pr_branch=self.app.destination.branch,
            title=pr_title_encoded,
        )
        self._print(
            "\nℹ️  You can still open the PR yourself there:\n" f"\t{new_pr_url}\n"
        )
        self._print_tips(pr_data)


class BranchesDiff(Output):
    """Helper to compare easily commits (and related PRs) between two branches."""

    def __init__(self, app):
        self.app = app
        self.path = self.app.addon_path
        self.from_branch_path_commits, _ = self._get_branch_commits(
            self.app.from_branch.ref(), self.path
        )
        self.from_branch_all_commits, _ = self._get_branch_commits(
            self.app.from_branch.ref()
        )
        self.to_branch_path_commits, _ = self._get_branch_commits(
            self.app.to_branch.ref(), self.path
        )
        self.to_branch_all_commits, _ = self._get_branch_commits(
            self.app.to_branch.ref()
        )
        self.commits_diff = self.get_commits_diff()
        self.serialized_diff = self._serialize_diff(self.commits_diff)
        # Once the analyze is done, we store the cache on disk
        self.app.cache.save()

    def _serialize_diff(self, commits_diff):
        data = {}
        for pr, commits in commits_diff["addon"].items():
            data[pr.number] = pr.to_dict()
            data[pr.number]["missing_commits"] = [commit.hexsha for commit in commits]
        return data

    def _get_branch_commits(self, branch, path="."):
        """Get commits from the local repository for the given `branch`.

        An optional `path` parameter can be set to limit commits to a given folder.
        This function also filters out undesirable commits (merge or translation
        commits...).

        Return two data structures:
            - a list of Commit objects `[Commit, ...]`
            - a dict of Commits objects grouped by SHA `{SHA: Commit, ...}`
        """
        commits = self.app.repo.iter_commits(branch, paths=path)
        commits_list = []
        commits_by_sha = {}
        for commit in commits:
            if self.app.cache.is_commit_ported(commit.hexsha):
                continue
            com = g.Commit(
                commit, addons_path=self.app.addons_rootdir, cache=self.app.cache
            )
            if self._skip_commit(com):
                continue
            commits_list.append(com)
            commits_by_sha[commit.hexsha] = com
        # Put ancestors at the beginning of the list to loop with
        # the expected order
        commits_list.reverse()
        return commits_list, commits_by_sha

    @staticmethod
    def _skip_commit(commit):
        """Check if a commit should be skipped or not.

        Merge or translations commits are skipped for instance, or commits
        updating only files/folders we do not want to port (pre-commit
        configuration, setuptools files...).
        """
        return (
            # Skip merge commit
            len(commit.parents) > 1
            or commit.author_email in AUTHOR_EMAILS_TO_SKIP
            or any([term in commit.summary for term in SUMMARY_TERMS_TO_SKIP])
            or all(path_to_skip(path) for path in commit.paths)
        )

    def print_diff(self, verbose=False):
        lines_to_print = []
        fake_pr = None
        i = 0
        key = "addon"
        for i, pr in enumerate(self.commits_diff[key], 1):
            if pr.number:
                lines_to_print.append(
                    f"{i}) {bc.BOLD}{bc.OKBLUE}{pr.ref}{bc.END} "
                    f"{bc.OKBLUE}{pr.title}{bc.ENDC}:"
                )
                lines_to_print.append(f"\tBy {pr.author}, merged at {pr.merged_at}")
            else:
                lines_to_print.append(f"{i}) {bc.BOLD}{bc.OKBLUE}w/o PR{bc.END}:")
                fake_pr = pr
            if verbose:
                pr_paths = ", ".join([f"{bc.DIM}{path}{bc.ENDD}" for path in pr.paths])
                lines_to_print.append(f"\t=> Updates: {pr_paths}")
            if pr.number:
                pr_paths_not_ported = ", ".join(
                    [f"{bc.OKBLUE}{path}{bc.ENDC}" for path in pr.paths_not_ported]
                )
                lines_to_print.append(f"\t=> Not ported: {pr_paths_not_ported}")
            lines_to_print.append(
                f"\t=> {bc.BOLD}{bc.OKBLUE}{len(self.commits_diff[key][pr])} "
                f"commit(s){bc.END} not (fully) ported"
            )
            if pr.number:
                lines_to_print.append(f"\t=> {pr.url}")
            if verbose or not pr.number:
                for commit in self.commits_diff[key][pr]:
                    lines_to_print.append(
                        f"\t\t{bc.DIM}{commit.hexsha[:8]} " f"{commit.summary}{bc.ENDD}"
                    )
        if fake_pr:
            # We have commits without PR, adapt the message
            i -= 1
            nb_commits = len(self.commits_diff[key][fake_pr])
            message = (
                f"{bc.BOLD}{bc.OKBLUE}{i} pull request(s){bc.END} "
                f"and {bc.BOLD}{bc.OKBLUE}{nb_commits} commit(s) w/o "
                f"PR{bc.END} related to '{bc.OKBLUE}{self.path}"
                f"{bc.ENDC}' to port from {self.app.from_branch.ref()} "
                f"to {self.app.to_branch.ref()}"
            )
        else:
            message = (
                f"{bc.BOLD}{bc.OKBLUE}{i} pull request(s){bc.END} "
                f"related to '{bc.OKBLUE}{self.path}{bc.ENDC}' to port from "
                f"{self.app.from_branch.ref()} to {self.app.to_branch.ref()}"
            )
        lines_to_print.insert(0, message)
        if self.commits_diff[key]:
            lines_to_print.insert(1, "")
        self._print("\n".join(lines_to_print))

    def print_satellite_diff(self, verbose=False):
        nb_prs = len(self.commits_diff["satellite"])
        if not nb_prs:
            return
        self._print()
        lines_to_print = []
        msg = (
            f"ℹ️  {nb_prs} other PRs related to {bc.OKBLUE}{self.app.addon}{bc.ENDC} "
            "are also updating satellite modules/root files"
        )
        if verbose:
            msg += ":"
        lines_to_print.append(msg)
        paths_ported = []
        paths_not_ported = []
        pr_paths_not_ported = sorted(
            set(
                itertools.chain.from_iterable(
                    [pr.paths_not_ported for pr in self.commits_diff["satellite"]]
                )
            )
        )
        for path in pr_paths_not_ported:
            path_exists = g.check_path_exists(
                self.app.repo,
                self.app.to_branch.ref(),
                path,
                rootdir=self.app.addons_rootdir and str(self.app.addons_rootdir),
            )
            if path_exists:
                if verbose:
                    lines_to_print.append(f"\t{bc.OKGREEN}- {path}{bc.END}")
                paths_ported.append(path)
            else:
                paths_not_ported.append(path)
        # Print the list of related modules/root files
        if verbose:
            if paths_not_ported:
                # Two cases:
                # - if we have PRs that could update already migrated modules
                #   we list them (see above) while displaying only a counter for
                #   not yet migrated modules.
                if paths_ported:
                    lines_to_print.append(
                        f"\t{bc.DIM}- +{len(paths_not_ported)} modules/root files "
                        f"not ported{bc.END}"
                    )
                # - if we get only PRs that could update non-migrated modules we
                #   do not display a counter but an exaustive list of these modules.
                else:
                    for path in paths_not_ported:
                        lines_to_print.append(f"\t{bc.DIM}- {path}{bc.END}")
            if paths_ported:
                lines_to_print.append("Think about running oca-port on these modules.")
        self._print("\n".join(lines_to_print))

    def get_commits_diff(self):
        """Returns the commits which do not exist in `to_branch`, grouped by
        their related Pull Request.

        These PRs are then in turn grouped based on their impacted addons:
            - if a PR is updating the analyzed module, it'll be put in 'addon' key
            - if a PR is updating satellite module(s), it'll be put in 'satellite' key

        :return: a dict {
            'addon': {PullRequest: {Commit: data, ...}, ...},
            'satellite': {PullRequest: {Commit: data, ...}, ...},
        }
        """
        commits_by_pr = defaultdict(list)
        fake_pr = g.PullRequest(*[""] * 6)
        # 1st loop to collect original PRs and stack orphaned commits in a fake PR
        for commit in self.from_branch_path_commits:
            if commit in self.to_branch_all_commits:
                self.app.cache.mark_commit_as_ported(commit.hexsha)
                continue
            # Get related Pull Request if any,
            # or fallback on a fake PR to host orphaned commits
            # This call has two effects:
            #   - put in cache original PRs (so the 2nd loop is faster)
            #   - stack orphaned commits in fake PR
            self._get_original_pr(commit, fallback_pr=fake_pr)
        # 2nd loop to actually analyze the content of commits/PRs
        for commit in self.from_branch_path_commits:
            if commit in self.to_branch_all_commits:
                self.app.cache.mark_commit_as_ported(commit.hexsha)
                continue
            # Get related Pull Request if any,
            # or fallback on a fake PR that hosts orphaned commits
            pr = self._get_original_pr(commit, fallback_pr=fake_pr)
            if pr:
                for pr_commit_sha in pr.commits:
                    try:
                        raw_commit = self.app.repo.commit(pr_commit_sha)
                    except ValueError:
                        # Ignore commits referenced by a PR but not present
                        # in the stable branches
                        continue
                    pr_commit = g.Commit(
                        raw_commit,
                        addons_path=self.app.addons_rootdir,
                        cache=self.app.cache,
                    )
                    if self._skip_commit(pr_commit):
                        continue
                    pr_commit_paths = {
                        path for path in pr_commit.paths if not path_to_skip(path)
                    }
                    pr.paths.update(pr_commit_paths)
                    # Check that this PR commit does not change the current
                    # addon we are interested in, in such case also check
                    # for each updated addons that the commit has already
                    # been ported.
                    # Indeed a commit could have been ported partially
                    # in the past (with git-format-patch), and we now want
                    # to port the remaining chunks.
                    if pr_commit not in self.to_branch_path_commits:
                        paths = set(pr_commit_paths)
                        # A commit could have been ported several times
                        # if it was impacting several addons and the
                        # migration has been done with git-format-patch
                        # on each addon separately
                        to_branch_all_commits = self.to_branch_all_commits[:]
                        skip_pr_commit = False
                        with g.no_strict_commit_equality():
                            while pr_commit in to_branch_all_commits:
                                index = to_branch_all_commits.index(pr_commit)
                                ported_commit = to_branch_all_commits.pop(index)
                                ported_commit_paths = {
                                    path
                                    for path in ported_commit.paths
                                    if not path_to_skip(path)
                                }
                                pr.ported_paths.update(ported_commit_paths)
                                pr_commit.ported_commits.append(ported_commit)
                                paths -= ported_commit_paths
                                if not paths:
                                    # The ported commits have already updated
                                    # the same addons than the original one,
                                    # we can skip it.
                                    skip_pr_commit = True
                        if skip_pr_commit:
                            continue
                    # We want to port commits that were still not ported
                    # for the addon we are interested in.
                    # If the commit has already been included, skip it.
                    if (
                        pr_commit in self.to_branch_path_commits
                        and pr_commit in self.to_branch_all_commits
                    ):
                        continue
                    existing_pr_commits = commits_by_pr.get(pr, [])
                    for existing_pr_commit in existing_pr_commits:
                        if (
                            existing_pr_commit == pr_commit
                            and existing_pr_commit.hexsha == pr_commit.hexsha
                        ):
                            # This PR commit has already been appended, skip
                            break
                    else:
                        commits_by_pr[pr].append(pr_commit)
        # Sort PRs on the merge date (better to port them in the right order).
        # Do not return blacklisted PR.
        sorted_commits_by_pr = {
            "addon": defaultdict(list),
            "satellite": defaultdict(list),
        }
        for pr in sorted(commits_by_pr, key=lambda pr: pr.merged_at or ""):
            if self._is_pr_updating_addon(pr):
                key = "addon"
            else:
                key = "satellite"
            blacklisted = self.app.storage.is_pr_blacklisted(pr.ref)
            if not blacklisted:
                # TODO: Backward compat for old tracking only by number
                blacklisted = self.app.storage.is_pr_blacklisted(pr.number)
            if blacklisted:
                msg = (
                    f"{bc.DIM}PR #{pr.number}" if pr.number else "Orphaned commits"
                ) + f" blacklisted ({blacklisted}){bc.ENDD}"
                self._print(msg)
                continue
            sorted_commits_by_pr[key][pr] = commits_by_pr[pr]
        return sorted_commits_by_pr

    def _is_pr_updating_addon(self, pr):
        """Check if a PR still needs to update the analyzed addon."""
        for path in pr.paths_not_ported:
            path_ = pathlib.Path(path)
            if path_.name == self.app.addon:
                return True
        return False

    def _get_original_pr(self, commit: g.Commit, fallback_pr=None):
        """Return the original PR of a given commit.

        If `fallback_pr` is provided, it'll be returned with the commit stacked in it.

        This method is taking care of storing in cache the original PR of a commit.
        """
        # Try to get the data from the user's cache first
        data = self.app.cache.get_pr_from_commit(commit.hexsha)
        if data:
            return g.PullRequest(**data)
        # Request GitHub to get them
        if not any("github.com" in remote.url for remote in self.app.repo.remotes):
            return self._handle_fallback_pr(fallback_pr, commit)
        src_repo_name = self.app.source.repo or self.app.repo_name
        try:
            # 1st attempt: detect original PR from source branch
            # (e.g. if source branch == 'master')
            raw_data = self.app.github.get_original_pr(
                self.app.upstream_org,
                src_repo_name,
                self.app.source.branch,
                commit.hexsha,
            )
            if not raw_data:
                # 2nd attempt: detect original PR from source version
                # (e.g. if working from a specific branch as source)
                raw_data = self.app.github.get_original_pr(
                    self.app.upstream_org,
                    src_repo_name,
                    self.app.source_version,
                    commit.hexsha,
                )
        except requests.exceptions.ConnectionError:
            self._print("⚠️  Unable to detect original PR (connection error)")
            return self._handle_fallback_pr(fallback_pr, commit)
        if raw_data:
            # Get all commits of the PR as they could update others addons
            # than the one the user is interested in.
            # NOTE: commits fetched from PR are already in the right order
            pr_number = raw_data["number"]
            pr_commits_data = self.app.github.request(
                f"repos/{self.app.upstream_org}/{src_repo_name}"
                f"/pulls/{pr_number}/commits?per_page=100"
            )
            pr_commits = [pr["sha"] for pr in pr_commits_data]
            data = {
                "number": raw_data["number"],
                "url": raw_data["html_url"],
                "author": raw_data["user"].get("login", ""),
                "title": raw_data["title"],
                "body": raw_data["body"],
                "merged_at": raw_data["merged_at"],
                "commits": pr_commits,
            }
            self.app.cache.store_commit_pr(commit.hexsha, data)
            return g.PullRequest(**data)
        return self._handle_fallback_pr(fallback_pr, commit)

    def _handle_fallback_pr(self, fallback_pr, commit):
        # Fallback PR hosting orphaned commits
        if fallback_pr:
            if commit.hexsha not in fallback_pr.commits:
                fallback_pr.commits.append(commit.hexsha)
        return fallback_pr
