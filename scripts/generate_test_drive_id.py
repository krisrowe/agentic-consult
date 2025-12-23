#!/usr/bin/env python3
"""Generate a deterministic synthetic Drive-ID-like token for tests.

Purpose and safety
------------------
This generator produces the same token every time when called with the same
seed. Tests should call this function instead of hardcoding long identifiers
that might accidentally match real production values in the repository.
Using a deterministic synthetic token avoids tripping the repo's own
pre-commit/scan logic while keeping test outputs stable and reproducible.

Token format
------------
- Characters: letters (upper/lower) and digits
- One underscore is inserted deterministically at `underscore_pos`
- `total_length` controls overall token length

Example (CLI)
-------------
Run this from the repository root to print the deterministic token used by
tests (same seed each run):

```bash
python3 -c "from scripts.generate_test_drive_id import generate_synthetic_drive_id; print(generate_synthetic_drive_id())"
```

If you need to change the seed for local experimentation, call
`generate_synthetic_drive_id(seed=...)`.
"""
import random
import string


def generate_synthetic_drive_id(seed=20251223, total_length=33, underscore_pos=20):
    random.seed(seed)
    chars = string.ascii_letters + string.digits
    # generate deterministic stream and insert underscore at position
    parts = [random.choice(chars) for _ in range(total_length - 1)]
    token = ''.join(parts[:underscore_pos]) + '_' + ''.join(parts[underscore_pos:])
    # ensure token has at least one digit and one letter; if not, tweak deterministically
    if not any(c.isdigit() for c in token) or not any(c.isalpha() for c in token):
        # flip one character deterministically
        token = list(token)
        token[0] = 'A'
        token[1] = '1'
        token = ''.join(token)
    return token


if __name__ == '__main__':
    print(generate_synthetic_drive_id())
