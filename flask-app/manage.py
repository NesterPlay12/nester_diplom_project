"""Administrative maintenance commands for the Flask application."""
import getpass
import re
import sys

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.models import db, User


def create_admin():
    app = create_app()
    with app.app_context():
        username = input('Administrator username: ').strip().lower()
        email = input('Administrator email: ').strip().lower()
        if not 3 <= len(username) <= 80:
            raise SystemExit('Username must be between 3 and 80 characters.')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(email) > 120:
            raise SystemExit('Enter a valid email address.')
        if User.query.filter(
            func.lower(User.username) == username.lower()
        ).first() or User.query.filter(func.lower(User.email) == email).first():
            raise SystemExit('A user with that username or email already exists.')

        password = getpass.getpass('Password (at least 12 characters): ')
        confirmation = getpass.getpass('Confirm password: ')
        if len(password) < 12:
            raise SystemExit('Password must contain at least 12 characters.')
        if password != confirmation:
            raise SystemExit('Passwords do not match.')

        administrator = User(username=username, email=email, role='admin', is_active=True)
        administrator.set_password(password)
        db.session.add(administrator)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise SystemExit('The account could not be created because the username or email is already used.')
        print('Administrator account created.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'create-admin':
        raise SystemExit('Usage: python manage.py create-admin')
    create_admin()
