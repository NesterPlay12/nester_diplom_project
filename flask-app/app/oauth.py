from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app):
    """Инициализирует OAuth и регистрирует провайдеров."""
    oauth.init_app(app)

    if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
        oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url=(
                'https://accounts.google.com/.well-known/openid-configuration'
            ),
            client_kwargs={
                'scope': 'openid email profile',
                'prompt': 'select_account',
            },
        )
