"""Manage Google sign-in membership from an operator-controlled shell."""

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from protohub.domain.settings import Settings
from protohub.persistence.auth import SessionRepository
from protohub.persistence.database import create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="Authorize an email for Google sign-in")
    add.add_argument("email")
    add.add_argument("--subject", help="Pin an independently verified Google subject")
    remove = commands.add_parser("remove", help="Revoke membership and its Google sessions")
    remove.add_argument("email")
    args = parser.parse_args(argv)
    try:
        repository = SessionRepository(create_session_factory(Settings().database_url))
        if args.command == "add":
            repository.add_account(args.email, args.subject)
        else:
            repository.remove_account(args.email)
    except ValueError:
        print("Invalid account details or conflicting Google identity.", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("Account update failed. Check database availability and migrations.", file=sys.stderr)
        return 1
    print("Account membership updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
