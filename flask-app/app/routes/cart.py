from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..models import db, CartItem, Product, Order, OrderItem

cart_bp = Blueprint('cart', __name__)


def _is_ajax():
    return request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _cart_error(message, status=400, product_id=None):
    if _is_ajax():
        return jsonify({'status': 'error', 'message': message}), status
    flash(message, 'danger')
    return redirect(url_for('main.product_detail', product_id=product_id) if product_id
                    else url_for('cart.view_cart'))


def _cart_quantity_for_product(product_id, excluding_item_id=None):
    query = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id)
    if excluding_item_id is not None:
        query = query.filter(CartItem.id != excluding_item_id)
    return sum(item.quantity for item in query.all())


@cart_bp.route('/')
@login_required
def view_cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in items if item.product)
    return render_template('cart.html', items=items, total=total)


@cart_bp.route('/add/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.is_active or not product.is_approved:
        return _cart_error('Этот товар сейчас недоступен.', 409, product_id)
    if product.stock <= 0:
        return _cart_error('Товара нет в наличии.', 409, product_id)

    try:
        quantity = int(request.form.get('quantity', '1'))
    except (TypeError, ValueError):
        return _cart_error('Укажите корректное количество.', 400, product_id)
    if quantity < 1:
        return _cart_error('Количество должно быть не меньше одного.', 400, product_id)

    selected_color = request.form.get('color', '').strip()
    selected_size = request.form.get('size', '').strip()
    if product.colors and not selected_color:
        selected_color = product.colors[0]
    if product.sizes and not selected_size:
        selected_size = product.sizes[0]
    if selected_color not in product.colors and (selected_color or product.colors):
        return _cart_error('Выберите доступный цвет товара.', 400, product_id)
    if selected_size not in product.sizes and (selected_size or product.sizes):
        return _cart_error('Выберите доступный размер товара.', 400, product_id)

    already_in_cart = _cart_quantity_for_product(product.id)
    if already_in_cart + quantity > product.stock:
        return _cart_error(
            f'Доступно для добавления: {max(product.stock - already_in_cart, 0)} шт.',
            409, product_id,
        )

    existing = CartItem.query.filter_by(
        user_id=current_user.id,
        product_id=product_id,
        selected_color=selected_color,
        selected_size=selected_size,
    ).first()
    if existing:
        existing.quantity += quantity
    else:
        db.session.add(CartItem(
            user_id=current_user.id,
            product_id=product_id,
            quantity=quantity,
            selected_color=selected_color,
            selected_size=selected_size,
        ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _cart_error('Корзина обновилась в другом запросе. Повторите действие.', 409, product_id)

    count = sum(
        item.quantity for item in CartItem.query.filter_by(user_id=current_user.id).all()
    )
    if _is_ajax():
        return jsonify({'status': 'ok', 'count': count})
    flash(f'"{product.name}" добавлен в корзину', 'success')
    return redirect(url_for('main.product_detail', product_id=product_id))


@cart_bp.route('/remove/<int:item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/update/<int:item_id>', methods=['POST'])
@login_required
def update_quantity(item_id):
    item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    try:
        quantity = int(request.form.get('quantity', '1'))
    except (TypeError, ValueError):
        flash('Укажите корректное количество', 'danger')
        return redirect(url_for('cart.view_cart'))

    if quantity < 1:
        db.session.delete(item)
    else:
        product = item.product
        if not product or not product.is_active or not product.is_approved:
            flash('Этот товар больше недоступен', 'danger')
            return redirect(url_for('cart.view_cart'))
        other_quantity = _cart_quantity_for_product(product.id, excluding_item_id=item.id)
        if quantity + other_quantity > product.stock:
            flash(f'Доступно не более {max(product.stock - other_quantity, 0)} шт.', 'warning')
            return redirect(url_for('cart.view_cart'))
        item.quantity = quantity
    db.session.commit()
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not items:
        flash('Ваша корзина пуста', 'warning')
        return redirect(url_for('cart.view_cart'))

    total = sum(item.product.price * item.quantity for item in items if item.product)
    if request.method == 'GET':
        unavailable = [
            item for item in items
            if not item.product
            or not item.product.is_active
            or not item.product.is_approved
            or item.product.stock < item.quantity
        ]
        if unavailable:
            flash('Проверьте наличие товаров в корзине перед оформлением заказа.', 'warning')
            return redirect(url_for('cart.view_cart'))
        return render_template('checkout.html', items=items, total=total)

    address = request.form.get('address', '').strip()
    phone = request.form.get('phone', '').strip()
    comment = request.form.get('comment', '').strip()
    if not address:
        flash('Укажите адрес доставки или выберите пункт выдачи', 'danger')
        return render_template('checkout.html', items=items, total=total), 400

    quantities = {}
    for item in items:
        product = item.product
        if not product or not product.is_active or not product.is_approved:
            flash('Один из товаров больше недоступен. Обновите корзину.', 'warning')
            return redirect(url_for('cart.view_cart'))
        if item.selected_color and item.selected_color not in product.colors:
            flash(f'Цвет товара «{product.name}» больше недоступен. Выберите его заново.', 'warning')
            return redirect(url_for('cart.view_cart'))
        if item.selected_size and item.selected_size not in product.sizes:
            flash(f'Размер товара «{product.name}» больше недоступен. Выберите его заново.', 'warning')
            return redirect(url_for('cart.view_cart'))
        quantities[product.id] = quantities.get(product.id, 0) + item.quantity

    order = Order(
        user_id=current_user.id,
        status='pending',
        total=total,
        address=address,
        phone=phone or current_user.phone,
        comment=comment,
    )
    db.session.add(order)
    db.session.flush()

    # Conditional updates prevent overselling when two checkouts race for stock.
    for product_id, quantity in quantities.items():
        result = db.session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.is_active.is_(True),
                Product.is_approved.is_(True),
                Product.stock >= quantity,
            )
            .values(stock=Product.stock - quantity)
        )
        if result.rowcount != 1:
            db.session.rollback()
            flash('Количество товара изменилось. Проверьте корзину и повторите заказ.', 'warning')
            return redirect(url_for('cart.view_cart'))

    for item in items:
        product = item.product
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            product_image=product.image_url,
            quantity=item.quantity,
            price=product.price,
            selected_color=item.selected_color or None,
            selected_size=item.selected_size or None,
        ))
        db.session.delete(item)

    db.session.commit()
    flash(f'Заказ #{order.id} успешно оформлен!', 'success')
    return redirect(url_for('account.order_detail', order_id=order.id))
