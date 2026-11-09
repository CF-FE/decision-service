"""Install one root-only Decision Service credential from standard input."""
import argparse
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credential", choices=["openai", "hindsight", "github-client-id", "github-client-secret"])
    credential = parser.parse_args().credential
    if os.geteuid() != 0:
        parser.exit(1, "Run on the service host as root.\n")
    directory = Path("/etc/decision-service")
    if not directory.is_dir():
        parser.exit(1, "Decision Service configuration directory is missing.\n")

    raw = sys.stdin.buffer.read(8193).rstrip(b"\r\n")
    prefix = f"DECISION_SERVICE_{credential.upper()}_API_KEY=".encode("ascii")
    key = raw.removeprefix(prefix)
    if ((raw.startswith(b"DECISION_SERVICE_") and not raw.startswith(prefix))
            or len(raw) >= 8193 or re.fullmatch(rb"[!-~]{12,4096}", key) is None):
        parser.exit(1, "Invalid provider credential input.\n")

    with NamedTemporaryFile(dir=directory, prefix=f".{credential}-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(key + b"\n")
            handle.close()
            temporary.replace(directory / f"{credential}.key")
        finally:
            temporary.unlink(missing_ok=True)
    print(f"{credential} credential installed")


if __name__ == "__main__":
    main()
