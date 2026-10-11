"""Generate a salted four-digit PIN hash for an administrator-assisted reset."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from security import hash_password, valid_pin, normalize_credential

def main():
    password=normalize_credential(getpass('New 4-digit PIN: '))
    if not valid_pin(password):
        print('Choose a PIN of exactly 4 digits.',file=sys.stderr)
        return 1
    confirmation=normalize_credential(getpass('Confirm new PIN: '))
    if password!=confirmation:
        print('PINs do not match.',file=sys.stderr)
        return 1
    print('\nCopy this entire hash into your account row in users.password:\n')
    print(hash_password(password))
    print('\nSign in using the 4-digit PIN you entered above, not this hash.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
