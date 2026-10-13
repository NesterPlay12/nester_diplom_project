import os
import re
from urllib.parse import unquote, urlparse
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from ..models import db, User
from ..oauth import oauth

auth_bp = Blueprint('auth', __name__)
_EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _safe_local_redirect(target):
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return None
    decoded_target = unquote(target)
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded_target):
        return None
    parsed = urlparse(decoded_target)
    if parsed.scheme or parsed.netloc or parsed.path.startswith('//') or '\\' in parsed.path:
        return None
    return target


# ─────────────────────────── Обычный вход ───────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('Ваш аккаунт заблокирован. Обратитесь в поддержку.', 'danger')
                return redirect(url_for('auth.login'))
            login_user(user, remember=remember)
            next_page = _safe_local_redirect(request.args.get('next', ''))
            flash(f'Добро пожаловать, {user.username}!', 'success')
            return redirect(next_page or url_for('main.index'))
        flash('Неверный email или пароль', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()

        if not username or not email or not password:
            flash('Заполните все обязательные поля', 'danger')
            return render_template('auth/register.html')
        if len(username) < 3 or len(username) > 80:
            flash('Имя пользователя должно содержать от 3 до 80 символов', 'danger')
            return render_template('auth/register.html')
        if len(email) > 120 or not _EMAIL_PATTERN.fullmatch(email):
            flash('Укажите корректный email', 'danger')
            return render_template('auth/register.html')
        if len(password) < 8:
            flash('Пароль должен содержать минимум 8 символов', 'danger')
            return render_template('auth/register.html')
        if len(phone) > 20:
            flash('Телефон слишком длинный', 'danger')
            return render_template('auth/register.html')
        if password != confirm:
            flash('Пароли не совпадают', 'danger')
            return render_template('auth/register.html')
        if User.query.filter(func.lower(User.email) == email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return render_template('auth/register.html')
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            flash('Это имя пользователя уже занято', 'danger')
            return render_template('auth/register.html')

        user = User(username=username.lower(), email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Аккаунт с таким email или именем пользователя уже существует', 'danger')
            return render_template('auth/register.html')
        login_user(user)
        flash('Регистрация прошла успешно! Добро пожаловать!', 'success')
        return redirect(url_for('main.index'))
    return render_template('auth/register.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Вы вышли из аккаунта', 'info')
    return redirect(url_for('main.index'))


# ─────────────────────────── Google OAuth ───────────────────────────

@auth_bp.route('/google')
def google_login():
    """Перенаправляет пользователя на страницу авторизации Google."""
    if not current_app.config.get('GOOGLE_CLIENT_ID') or not current_app.config.get('GOOGLE_CLIENT_SECRET'):
        flash('Вход через Google временно недоступен. Используйте email и пароль.', 'warning')
        return redirect(url_for('auth.login'))

    redirect_uri = (
        current_app.config.get('GOOGLE_REDIRECT_URI')
        or url_for('auth.google_callback', _external=True)
    )
    # Сохраняем next, чтобы вернуться после логина
    session['oauth_next'] = _safe_local_redirect(request.args.get('next', '')) or ''
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback')
def google_callback():
    """Обрабатывает ответ от Google, создаёт или авторизует пользователя."""
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        current_app.logger.exception('Google OAuth token exchange failed')
        flash('Ошибка авторизации через Google. Попробуйте ещё раз.', 'danger')
        return redirect(url_for('auth.login'))

    user_info = token.get('userinfo')
    if not user_info:
        try:
            user_info = oauth.google.userinfo(token=token)
        except Exception:
            current_app.logger.exception('Google userinfo request failed')
            user_info = {}
    if hasattr(user_info, 'json'):
        user_info = user_info.json()
    if not isinstance(user_info, dict):
        user_info = {}
    google_id = user_info.get('sub')
    email_value = user_info.get('email', '')
    email = email_value.strip().lower() if isinstance(email_value, str) else ''
    name_value = user_info.get('name', '')
    name = name_value if isinstance(name_value, str) and name_value else email.split('@')[0]
    avatar_value = user_info.get('picture', '')
    avatar = avatar_value if isinstance(avatar_value, str) and len(avatar_value) <= 255 else ''

    email_verified = user_info.get('email_verified') is True or str(
        user_info.get('email_verified', '')
    ).lower() == 'true'
    if (
        not google_id
        or len(str(google_id)) > 100
        or not _EMAIL_PATTERN.fullmatch(email)
        or not email_verified
    ):
        flash('Не удалось получить данные от Google.', 'danger')
        return redirect(url_for('auth.login'))

    # 1. Ищем по google_id
    user = User.query.filter_by(google_id=google_id).first()
    if user and not user.is_active:
        db.session.rollback()
        flash('Ваш аккаунт заблокирован. Обратитесь в поддержку.', 'danger')
        return redirect(url_for('auth.login'))

    if not user:
        # 2. Ищем по email — привязываем Google к существующему аккаунту
        user = User.query.filter(func.lower(User.email) == email).first()
        if user:
            if not user.is_active:
                db.session.rollback()
                flash('Ваш аккаунт заблокирован. Обратитесь в поддержку.', 'danger')
                return redirect(url_for('auth.login'))
            user.google_id = google_id
            if avatar and not user.avatar_url:
                user.avatar_url = avatar
        else:
            # 3. Создаём нового пользователя
            base = name.replace(' ', '_').lower()
            # Оставляем только безопасные символы, обрезаем до 25 знаков
            base = ''.join(c for c in base if c.isalnum() or c == '_')[:25] or 'user'
            username = base
            counter = 1
            while User.query.filter(func.lower(User.username) == username.lower()).first():
                username = f"{base}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                google_id=google_id,
                avatar_url=avatar,
                has_local_password=False,
            )
            # Ставим неугадываемый случайный хэш — пароль через Google не используется
            user.password_hash = generate_password_hash(os.urandom(32).hex())
            db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            current_app.logger.warning('Google account link/create conflicted with an existing account')
            flash('Не удалось связать аккаунт. Попробуйте войти по email и паролю.', 'warning')
            return redirect(url_for('auth.login'))

    login_user(user, remember=True)
    flash(f'Добро пожаловать, {user.username}!', 'success')

    next_page = session.pop('oauth_next', '')
    return redirect(_safe_local_redirect(next_page) or url_for('main.index'))
