"""Local account provisioning and configuration checks without service/model I/O."""

import argparse
from getpass import getpass

from .auth import password_hash
from .settings import ApplicationSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["hash-password", "check-config"])
    args = parser.parse_args()
    if args.action == "hash-password":
        print(password_hash(getpass("Password: ")))
    else:
        settings = ApplicationSettings()
        for account in settings.accounts.values():
            if account.get("role") not in {"viewer", "operator", "approver", "admin"}:
                raise ValueError("Account role is invalid")
            if not all(account.get(key) for key in ("organization_id", "user_id", "password_hash")):
                raise ValueError("Account identity or password hash is missing")
        print("Application configuration loaded; no services or providers were contacted.")


if __name__ == "__main__":
    main()
