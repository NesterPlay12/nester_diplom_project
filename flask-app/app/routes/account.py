from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from ..models import db, User, Order, Favorite

account_bp = Blueprint('account', __name__)


@account_bp.route('/')
@login_required
def profile():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).limit(5).all()
    return render_template('account/profile.html', orders=orders)


@account_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.username = request.form.get('username', current_user.username).strip()
        current_user.phone = request.form.get('phone', '').strip()
        current_user.address = request.form.get('address', '').strip()

        new_password = request.form.get('new_password', '').strip()
        if new_password:
            old_password = request.form.get('old_password', '')
            if not current_user.check_password(old_password):
                flash('Неверный текущий пароль', 'danger')
                return render_template('account/settings.html')
            if new_password != request.form.get('confirm_password', ''):
                flash('Пароли не совпадают', 'danger')
                return render_template('account/settings.html')
            current_user.set_password(new_password)

        db.session.commit()
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
        order.status = 'cancelled'
        db.session.commit()
        flash(f'Заказ #{order.id} отменён', 'info')
    return redirect(url_for('account.order_detail', order_id=order_id))


@account_bp.route('/favorites')
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template('account/favorites.html', favorites=favs)
