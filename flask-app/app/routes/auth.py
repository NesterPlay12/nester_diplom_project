from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from ..models import db, User

auth_bp = Blueprint('auth', __name__)


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
