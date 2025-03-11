import subprocess
from .utils.misc import Output, bcolors as bc
import click
import tempfile
import os
from .utils import git as g


class SquashBotCommits(Output):
    """
    Interactive squash for these commits:
        1) Bot commit: squashed into the "real" commit that generates them
        2) Translation commit: squashed into commits that translate the same language and come from the same author
    """

    def __init__(self, app) -> None:
        self.app = app
        self.all_commits, self.commits_by_sha = self._get_all_commits()
        self.skipped_commits = []

    def run(self):
        if self.app.non_interactive or self.app.dry_run:
            return False
        click.echo(
            click.style(
                "🚀 Starting reducing number of commits...",
                bold=True,
            ),
        )
        squashable_commits = self._get_squashable_commits()
        while len(squashable_commits) > 0:
            commit = squashable_commits.pop(0)
            squashed_into_commits = self._get_squashed_into_commits(commit)
            if not squashed_into_commits:
                self.skipped_commits.append(commit)
                continue
            result = self.squash(commit, squashed_into_commits)
            if not result:
                confirm = "Skip this commit?"
                if click.confirm(confirm):
                    self.skipped_commits.append(commit)
                    print(
                        f"\nSkipped {bc.OKCYAN}{commit.hexsha[:7]}{bc.ENDC} {commit.summary}\n"
                    )
            # update to get new SHAs
            self.all_commits, self.commits_by_sha = self._get_all_commits()
            squashable_commits = self._get_squashable_commits()
            print("\n")

    def _get_squashed_into_commits(self, target_commit):
        """Return commits that target_commit can be squashed into"""
        result = []
        # find commits for the same language coming from the same author.
        if target_commit._is_translation_commit():
            valid_commits = []
            valid_commits = [
                c
                for c in self.all_commits
                if c._is_same_language(target_commit)
                and c not in result
                and c != target_commit
            ]
            if valid_commits:
                result.extend(valid_commits)

        elif target_commit._is_bot_commit():
            # traverse to find real commit that generates bot commits
            parent_commit = target_commit.parents[0]
            com = self.commits_by_sha.get(parent_commit, None)
            while com:
                if (
                    com
                    and not com._is_bot_commit()
                    and not com._is_translation_commit()
                ):
                    result.append(com)
                    break
                parent_commit = com.parents[0]
                com = self.commits_by_sha.get(parent_commit, None)
        return result

    def _get_all_commits(self):
        """Get commits from the local repository for current branch.
        Return two data structures:
            - a list of Commit objects `[Commit, ...]`
            - a dict of Commits objects grouped by SHA `{SHA: Commit, ...}`
        """
        commits = self.app.repo.iter_commits(f"{self.app.target_version}...HEAD")
        commits_list = []
        commits_by_sha = {}
        for commit in commits:
            com = g.Commit(
                commit, addons_path=self.app.addons_rootdir, cache=self.app.cache
            )
            commits_list.append(com)
            commits_by_sha[commit.hexsha] = com
        return commits_list, commits_by_sha

    def _get_squashable_commits(self):
        result = [
            commit
            for commit in self.all_commits
            if (commit._is_bot_commit() or commit._is_translation_commit)
            and not self.is_skipped_commit(commit)
        ]
        return result

    def squash(self, commit, squashable_commits):
        self._print(
            f"Squashing {bc.OKCYAN}{commit.hexsha[:7]}{bc.ENDC} {commit.summary}"
        )
        available_commits = [c for c in squashable_commits if c.hexsha != commit.hexsha]
        self._print(f"0) {bc.BOLD}Skip this commit{bc.END}")
        for idx, c in enumerate(available_commits):
            self._print(f"{idx + 1}) {bc.OKCYAN}{c.hexsha[:7]}{bc.ENDC} {c.summary}")

        def is_valid(val):
            try:
                value = int(val)
            except ValueError:
                raise click.BadParameter("Please enter a valid number.")

            if value < 0 or value > len(available_commits):
                raise click.BadParameter("Please enter a valid number.")
            return value

        choice = click.prompt(
            "Select a commit to squash into:",
            default=0,
            value_proc=is_valid,
        )
        if not choice:  # if choice = 0
            self.skipped_commits.append(commit)
            return False
        selected_commit = available_commits[choice - 1]
        reorder = selected_commit.hexsha != commit.parents[0]
        return self._squash(commit, selected_commit, reorder)

    def _squash(self, commit, target_commit, reorder=False):
        base_commit = target_commit.parents[0]
        confirm = "\n".join(
            [
                "\nCommits to Squash:",
                f"\t{bc.OKCYAN}{commit.hexsha[:7]}{bc.ENDC} {commit.summary}",
                f"\t{bc.OKCYAN}{target_commit.hexsha[:7]}{bc.ENDC} {target_commit.summary}\n",
            ]
        )
        if not click.confirm(confirm):
            return False
        editor_script = ""
        if reorder:
            with tempfile.NamedTemporaryFile(delete=False, mode="w") as temp_file:
                editor_script = temp_file.name
                temp_file.write(
                    f"""#!/bin/bash
                    todo_file=".git/rebase-merge/git-rebase-todo"
                    tmp_file="$todo_file.tmp"

                    # Copy todo_file to a temporary file
                    cp "$todo_file" "$tmp_file"
                    printf "%s\\n" "/^pick {commit.hexsha[:7]}/ m1" "wq" | ed -s "$tmp_file"
                    printf "%s\\n" "/^pick {commit.hexsha[:7]} /s//squash {commit.hexsha[:7]} /" "wq" | ed -s "$tmp_file"
                    mv "$tmp_file" "$todo_file"
                    """
                )
            os.chmod(editor_script, 0o755)
            result = subprocess.run(
                f"GIT_SEQUENCE_EDITOR='{editor_script}' GIT_EDITOR=true git rebase -i {base_commit}",
                capture_output=True,
                shell=True,
            )
        else:
            command = f"GIT_SEQUENCE_EDITOR='sed -i \"s/^pick {commit.hexsha[:7]} /squash {commit.hexsha[:7]} /\"' GIT_EDITOR=true git rebase -i {base_commit}"
            result = subprocess.run(command, capture_output=True, shell=True)
        output = result.stdout.decode("utf-8")
        if editor_script:
            os.remove(editor_script)

        if "CONFLICT" in output:
            self._print(f"\n{bc.FAIL}ERROR: A conflict occurs{bc.ENDC}")
            self._print(
                "\n ⚠️You can't squash those commits together and they should be left as is"
            )
            self._abort_rebase()
            return False
        click.echo(
            click.style(
                "✨ Done! Successfully squashed.",
                fg="green",
                bold=True,
            )
        )
        return True

    def _abort_rebase(self):
        self.app.repo.git.rebase("--abort")

    def is_skipped_commit(self, commit):
        return commit in self.skipped_commits
