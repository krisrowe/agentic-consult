"""Test utilities: deterministic synthetic Drive-ID generator.

Place test-only helpers here to avoid copying production-looking tokens
into tracked files. Use the same deterministic seed in tests so outputs
are stable and reproducible.
"""
import random
import string


def generate_synthetic_drive_id(seed=20251223, total_length=33, underscore_pos=20):
    """Return a deterministic Drive-ID-like token for tests.

    - `seed` controls determinism
    - `total_length` total characters including underscore
    - `underscore_pos` index where underscore is inserted
    """
    random.seed(seed)
    chars = string.ascii_letters + string.digits
    parts = [random.choice(chars) for _ in range(total_length - 1)]
    token = ''.join(parts[:underscore_pos]) + '_' + ''.join(parts[underscore_pos:])
    if not any(c.isdigit() for c in token) or not any(c.isalpha() for c in token):
        token = list(token)
        token[0] = 'A'
        token[1] = '1'
        token = ''.join(token)
    return token


if __name__ == '__main__':
    print(generate_synthetic_drive_id())
