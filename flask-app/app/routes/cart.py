from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from ..models import db, CartItem, Product, Order, OrderItem

cart_bp = Blueprint('cart', __name__)


@cart_bp.route('/')
@login_required
def view_cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in items if item.product)
    return render_template('cart.html', items=items, total=total)


@cart_bp.route('/add/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = request.form.get('quantity', 1, type=int)
    if quantity < 1:
        quantity = 1
    existing = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        existing.quantity = min(existing.quantity + quantity, product.stock or 99)
    else:
        item = CartItem(user_id=current_user.id, product_id=product_id, quantity=quantity)
        db.session.add(item)
    db.session.commit()
    count = CartItem.query.filter_by(user_id=current_user.id).count()
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
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
    qty = request.form.get('quantity', 1, type=int)
    if qty < 1:
        db.session.delete(item)
    else:
        item.quantity = qty
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

    if request.method == 'POST':
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        comment = request.form.get('comment', '').strip()
        if not address:
            flash('Укажите адрес доставки', 'danger')
            return render_template('checkout.html', items=items, total=total)

        order = Order(
            user_id=current_user.id,
            status='pending',
            total=total,
            address=address,
            phone=phone or current_user.phone,
            comment=comment
        )
        db.session.add(order)
        db.session.flush()

        for item in items:
            if item.product:
                oi = OrderItem(
                    order_id=order.id,
                    product_id=item.product_id,
                    product_name=item.product.name,
                    product_image=item.product.image_url,
                    quantity=item.quantity,
                    price=item.product.price
                )
                db.session.add(oi)
                if item.product.stock:
                    item.product.stock = max(0, item.product.stock - item.quantity)
            db.session.delete(item)

        db.session.commit()
        flash(f'Заказ #{order.id} успешно оформлен!', 'success')
        return redirect(url_for('account.order_detail', order_id=order.id))

    return render_template('checkout.html', items=items, total=total)
