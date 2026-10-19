from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from ..models import db, User, Order, Favorite
from ..services.orders import transition_order

account_bp = Blueprint('account', __name__)


@account_bp.route('/profile')
@account_bp.route('/')
@login_required
def profile():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).limit(5).all()
    return render_template('account/profile.html', orders=orders)


@account_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        username = request.form.get('username', current_user.username).strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        if len(username) < 3 or len(username) > 80:
            flash('Имя пользователя должно содержать от 3 до 80 символов', 'danger')
            return render_template('account/settings.html'), 400
        if len(phone) > 20 or len(address) > 500:
            flash('Телефон или адрес превышает допустимую длину', 'danger')
            return render_template('account/settings.html'), 400
        existing_username = User.query.filter(
            func.lower(User.username) == username.lower(),
            User.id != current_user.id,
        ).first()
        if existing_username:
            flash('Это имя пользователя уже занято', 'danger')
            return render_template('account/settings.html')
        new_password = request.form.get('new_password', '')
        if new_password:
            if len(new_password) < 8:
                flash('Новый пароль должен содержать минимум 8 символов', 'danger')
                return render_template('account/settings.html')
            old_password = request.form.get('old_password', '')
            # Для аккаунта, созданного через Google, текущего пароля может не быть:
            # авторизованный Google-пользователь может задать его впервые.
            has_google_only_auth = bool(
                current_user.google_id and not current_user.has_local_password and not old_password
            )
            if not has_google_only_auth and not current_user.check_password(old_password):
                flash('Неверный текущий пароль', 'danger')
                return render_template('account/settings.html')
            if new_password != request.form.get('confirm_password', ''):
                flash('Пароли не совпадают', 'danger')
                return render_template('account/settings.html')
            current_user.set_password(new_password)
            current_user.has_local_password = True

        current_user.username = username.lower()
        current_user.phone = phone
        current_user.address = address
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Это имя пользователя уже занято', 'danger')
            return render_template('account/settings.html'), 400
        flash('Данные сохранены', 'success')
    return render_template('account/settings.html')


@account_bp.route('/orders')
@login_required
def orders():
    page = request.args.get('page', 1, type=int)
    pagination = Order.query.filter_by(user_id=current_user.id).order_by(
        Order.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('account/orders.html', pagination=pagination)


@account_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    return render_template('account/order_detail.html', order=order)


@account_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if order.status not in ('pending', 'confirmed'):
        flash('Этот заказ нельзя отменить', 'danger')
    else:
        if not transition_order(order, 'cancelled'):
            flash('Этот заказ нельзя отменить', 'danger')
            return redirect(url_for('account.order_detail', order_id=order_id))
        db.session.commit()
        flash(f'Заказ #{order.id} отменён', 'info')
    return redirect(url_for('account.order_detail', order_id=order_id))


@account_bp.route('/favorites')
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template('account/favorites.html', favorites=favs)
