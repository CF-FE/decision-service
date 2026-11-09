"""Collect Decision Service credentials into owner-only files for a secure handoff."""
import argparse
import getpass
import os
import re
import sys
import warnings
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=["openai", "hindsight", "cloud"])
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    cloud = args.provider == "cloud"
    directory = args.destination if cloud else args.destination.parent
    parent = directory.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        parser.exit(1, "Use an owner-only directory.\n")
    if not cloud and args.destination.exists():
        parser.exit(1, "Destination already exists.\n")
    if not sys.stdin.isatty():
        parser.exit(1, "Use an interactive terminal.\n")

    targets = (
        [(directory / "openai.env", "OpenAI API key", "DECISION_SERVICE_OPENAI_API_KEY="),
         (directory / "github-client-id.key", "GitHub OAuth App Client ID", ""),
         (directory / "github-client-secret.key", "GitHub OAuth App Client Secret", "")]
        if cloud else
        [(args.destination, f"{args.provider} API key", f"DECISION_SERVICE_{args.provider.upper()}_API_KEY=")]
    )
    staged = []
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        for path, prompt, prefix in targets:
            if cloud and path.exists():
                existing = path.stat()
                if path.is_symlink() or existing.st_uid != os.getuid() or existing.st_mode & 0o077:
                    parser.exit(1, "Existing credential is outside the private file boundary.\n")
                continue
            key = getpass.getpass(f"{prompt} (input hidden): ")
            if not re.fullmatch(r"[!-~]{12,4096}", key):
                parser.exit(1, "Invalid credential input.\n")
            staged.append((path, prefix + key))

    for path, value in staged:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            parser.exit(1, "Destination already exists.\n")
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(value + "\n")
    print(f"{len(staged)} credential file(s) staged. Existing files were preserved.")


if __name__ == "__main__":
    main()
