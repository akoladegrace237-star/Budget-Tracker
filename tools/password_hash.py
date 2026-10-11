"""Generate a salted account password hash for an administrator-assisted reset."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from security import hash_password, strong_password

def main():
    password=getpass('New account password (12–128 characters): ')
    if not strong_password(password):
        print('Choose a password of 12–128 characters.',file=sys.stderr)
        return 1
    confirmation=getpass('Confirm new password: ')
    if password!=confirmation:
        print('Passwords do not match.',file=sys.stderr)
        return 1
    print('\nCopy this entire hash into your account row in users.password:\n')
    print(hash_password(password))
    print('\nSign in using the password you entered above, not this hash.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
