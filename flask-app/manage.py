"""Administrative maintenance commands for the Flask application."""
import getpass
import re
import sys
import argparse

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
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('create-admin')
    commands.add_parser('init-schema', help='Development schema only; never run on production')
    commands.add_parser('restore-development', help='Restore verified backup only into empty development PG')
    transfer = commands.add_parser('import-sqlite', help='Development-only lossless import')
    transfer.add_argument('source')
    transfer.add_argument('--backup-dir', default='../generated-artifacts/database-backups')
    args = parser.parse_args()
    if args.command == 'create-admin':
        create_admin()
    else:
        from app.services.database_transfer import require_development, transfer_sqlite, restore_development
        require_development()
        app = create_app({'TESTING': args.command == 'init-schema'})
        with app.app_context():
            if args.command == 'init-schema':
                from app import _database_initialization_lock, _run_migrations
                from sqlalchemy import text
                import os
                schema = os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket')
                with db.engine.begin() as connection:
                    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                with _database_initialization_lock():
                    db.create_all()
                    _run_migrations()
                print('Development schema initialized.')
            elif args.command == 'restore-development':
                from pathlib import Path
                restore_development(Path(__file__).parent / 'migration-manifest.json')
            else:
                transfer_sqlite(args.source, args.backup_dir)
