"""Password hashing for website sign-in (bcrypt, the same as the web app's users table)."""

import bcrypt

MIN_LENGTH = 10


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except ValueError:
        return False
