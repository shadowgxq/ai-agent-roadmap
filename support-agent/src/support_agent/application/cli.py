"""Local account provisioning and configuration checks without service/model I/O."""

import argparse
from getpass import getpass

from .auth import password_hash
from .settings import ApplicationSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["hash-password", "check-config", "migrate"])
    args = parser.parse_args()
    if args.action == "hash-password":
        print(password_hash(getpass("Password: ")))
    elif args.action == "migrate":
        import asyncio
        from alembic import command
        from alembic.config import Config
        from support_agent.config.settings import PROJECT_ROOT
        from support_agent.persistence import create_checkpointer
        settings = ApplicationSettings()
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
        async def initialize():
            async with create_checkpointer(settings.database_url):
                pass
        asyncio.run(initialize())
    else:
        settings = ApplicationSettings()
        if not settings.accounts:
            raise ValueError("Provision at least one server-side account")
        for account in settings.accounts.values():
            if account.get("role") not in {"viewer", "operator", "approver", "admin"}:
                raise ValueError("Account role is invalid")
            if not all(account.get(key) for key in ("organization_id", "user_id", "password_hash")):
                raise ValueError("Account identity or password hash is missing")
            salt, digest = account["password_hash"].split(":")
            if len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 64:
                raise ValueError("Account password hash is not a generated scrypt hash")
        print("Application configuration loaded; no services or providers were contacted.")


if __name__ == "__main__":
    main()
