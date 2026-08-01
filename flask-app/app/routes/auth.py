import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from ..models import db, User
from ..oauth import oauth

auth_bp = Blueprint('auth', __name__)


# ─────────────────────────── Обычный вход ───────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('Ваш аккаунт заблокирован. Обратитесь в поддержку.', 'danger')
                return redirect(url_for('auth.login'))
            login_user(user, remember=remember)
            next_page = request.args.get('next')
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
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()

        if not username or not email or not password:
            flash('Заполните все обязательные поля', 'danger')
            return render_template('auth/register.html')
        if password != confirm:
            flash('Пароли не совпадают', 'danger')
            return render_template('auth/register.html')
        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return render_template('auth/register.html')
        if User.query.filter_by(username=username).first():
            flash('Это имя пользователя уже занято', 'danger')
            return render_template('auth/register.html')

        user = User(username=username, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Регистрация прошла успешно! Добро пожаловать!', 'success')
        return redirect(url_for('main.index'))
    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из аккаунта', 'info')
    return redirect(url_for('main.index'))


# ─────────────────────────── Google OAuth ───────────────────────────

@auth_bp.route('/google')
def google_login():
    """Перенаправляет пользователя на страницу авторизации Google."""
    redirect_uri = url_for('auth.google_callback', _external=True)
    # Сохраняем next, чтобы вернуться после логина
    session['oauth_next'] = request.args.get('next', '')
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback')
def google_callback():
    """Обрабатывает ответ от Google, создаёт или авторизует пользователя."""
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        flash('Ошибка авторизации через Google. Попробуйте ещё раз.', 'danger')
        return redirect(url_for('auth.login'))

    user_info = token.get('userinfo', {})
    google_id = user_info.get('sub')
    email = user_info.get('email', '').strip()
    name = user_info.get('name', '') or email.split('@')[0]
    avatar = user_info.get('picture', '')

    if not google_id or not email:
        flash('Не удалось получить данные от Google.', 'danger')
        return redirect(url_for('auth.login'))

    # 1. Ищем по google_id
    user = User.query.filter_by(google_id=google_id).first()

    if not user:
        # 2. Ищем по email — привязываем Google к существующему аккаунту
        user = User.query.filter_by(email=email).first()
        if user:
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
            while User.query.filter_by(username=username).first():
                username = f"{base}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                google_id=google_id,
                avatar_url=avatar,
            )
            # Ставим неугадываемый случайный хэш — пароль через Google не используется
            user.password_hash = generate_password_hash(os.urandom(32).hex())
            db.session.add(user)

        db.session.commit()

    if not user.is_active:
        flash('Ваш аккаунт заблокирован. Обратитесь в поддержку.', 'danger')
        return redirect(url_for('auth.login'))

    login_user(user, remember=True)
    flash(f'Добро пожаловать, {user.username}!', 'success')

    next_page = session.pop('oauth_next', '') or url_for('main.index')
    return redirect(next_page)
