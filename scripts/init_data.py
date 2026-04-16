"""Database seed-data initializer.

Called by `make init-db` and `make dev-setup`. Currently a no-op — there is
no seed data required for local development. Add real seeding logic here if
the app grows to need it (e.g. default user roles, sample workbooks).
"""

from __future__ import annotations

import sys


def main() -> int:
    print("init_data: no seed data required — skipping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
