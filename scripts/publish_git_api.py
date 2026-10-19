"""Explicit, lossless GitHub publication fallback for restricted environments.

Try ordinary git push first. This script uses official Git Data API, verifies exact
Git object SHA, and advances an existing branch without force. It does not read or
print credentials. gh must already be authorized. Never initializes empty remotes.
"""

import argparse
import json
import subprocess


def git(*args):
    return subprocess.check_output(["git", *args])


def api(path, body=None, method="POST"):
    command = ["gh", "api", path]
    if body is not None:
        command += ["--method", method, "--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(body).encode() if body is not None else None,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Do not echo raw credential-helper or remote response text.
        raise RuntimeError(
            "GitHub Git Data API rejected request; inspect gh authorization and repository permissions"
        )
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-api-fallback", action="store_true")
    args = parser.parse_args()
    if not args.allow_api_fallback:
        parser.error("Try git push first, then explicitly opt in to this fallback")
    if git("status", "--porcelain").strip():
        parser.error("Commit or preserve outstanding changes before publishing")
    branch = git("branch", "--show-current").decode().strip()
    if branch != "master":
        parser.error("This project fallback currently publishes only master")
    repo = "repos/IgorKramar/codex_chronicle"
    remote = api(repo + "/git/ref/heads/master")["object"]["sha"]
    subprocess.run(["git", "fetch", "origin", "master"], check=True)
    if git("rev-parse", "origin/master").decode().strip() != remote:
        parser.error("Remote changed concurrently; fetch and inspect before retrying")
    subprocess.run(["git", "merge-base", "--is-ancestor", remote, "HEAD"], check=True)
    commits = git("rev-list", "--reverse", remote + "..HEAD").decode().splitlines()
    for sha in commits:
        entries = []
        for line in git("ls-tree", "-r", sha).decode().splitlines():
            meta, path = line.split("\t", 1)
            mode, kind, blob = meta.split()
            if kind != "blob":
                raise RuntimeError("Submodules are not supported by this publication helper")
            entries.append(
                {
                    "path": path,
                    "mode": mode,
                    "type": "blob",
                    "content": git("cat-file", "blob", blob).decode("utf-8"),
                }
            )
        tree = api(repo + "/git/trees", {"tree": entries})
        expected = git("rev-parse", sha + "^{tree}").decode().strip()
        if tree["sha"] != expected:
            raise RuntimeError("Tree SHA mismatch: branch was not advanced")
        headers, message = git("cat-file", "commit", sha).decode().split("\n\n", 1)
        if any(line.startswith(("gpgsig ", "encoding ")) for line in headers.splitlines()):
            raise RuntimeError(
                "Signed/encoded commits need ordinary Git transport; refuse conversion"
            )

        def person(fields, commit_sha=sha):
            values = (
                git("show", "-s", "--format=" + fields, commit_sha)
                .decode()
                .rstrip("\n")
                .split("\x00")
            )
            return dict(zip(("name", "email", "date"), values, strict=True))

        body = {
            "message": message,
            "tree": expected,
            "parents": [
                h.split(" ", 1)[1] for h in headers.splitlines() if h.startswith("parent ")
            ],
            "author": person("%an%x00%ae%x00%aI"),
            "committer": person("%cn%x00%ce%x00%cI"),
        }
        created = api(repo + "/git/commits", body)
        if created["sha"] != sha:
            raise RuntimeError("Commit SHA mismatch: branch was not advanced")
        print("Verified exact commit " + sha, flush=True)
    head = git("rev-parse", "HEAD").decode().strip()
    api(repo + "/git/refs/heads/master", {"sha": head, "force": False}, "PATCH")
    subprocess.run(["git", "fetch", "origin", "master"], check=True)
    if git("rev-parse", "origin/master").decode().strip() != head:
        raise RuntimeError("Remote verification failed")
    print("Published and verified " + head)


if __name__ == "__main__":
    main()
