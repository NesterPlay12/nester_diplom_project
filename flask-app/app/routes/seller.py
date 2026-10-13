from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from functools import wraps
from ..models import db, Product, Category, Order, OrderItem
from ..services.product_input import apply_product_form, parse_product_form

seller_bp = Blueprint('seller', __name__)


def seller_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_seller:
            flash('Доступ только для продавцов', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@seller_bp.route('/')
@login_required
@seller_required
def dashboard():
    products = Product.query.filter_by(seller_id=current_user.id).all()
    product_ids = [p.id for p in products]
    sold_items = (
        OrderItem.query.join(Order, Order.id == OrderItem.order_id)
        .filter(OrderItem.product_id.in_(product_ids), Order.status == 'delivered')
        .all()
        if product_ids else []
    )
    revenue = sum(i.price * i.quantity for i in sold_items)
    active_count = sum(1 for p in products if p.is_active and p.is_approved)
    pending_count = sum(1 for p in products if p.is_active and not p.is_approved)
    return render_template('seller/dashboard.html', products=products, revenue=revenue,
                           active_count=active_count, pending_count=pending_count,
                            sold_count=sum(i.quantity for i in sold_items))


@seller_bp.route('/products')
@login_required
@seller_required
def products():
    items = Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc()).all()
    return render_template('seller/products.html', products=items)


@seller_bp.route('/products/add', methods=['GET', 'POST'])
@login_required
@seller_required
def add_product():
    categories = Category.query.order_by(Category.parent_id, Category.name).all()
    if request.method == 'POST':
        values, errors = parse_product_form(request.form)
        if errors:
            flash(' '.join(errors), 'danger')
            return render_template('seller/add_product.html', categories=categories), 400
        product = Product(seller_id=current_user.id, is_active=True, is_approved=False)
        apply_product_form(product, values)
        if not product.image_url:
            product.image_url = '/static/images/product-placeholder.svg'
        db.session.add(product)
        db.session.commit()
        flash('Товар отправлен на модерацию', 'success')
        return redirect(url_for('seller.products'))
    return render_template('seller/add_product.html', categories=categories)


@seller_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@seller_required
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, seller_id=current_user.id).first_or_404()
    categories = Category.query.order_by(Category.parent_id, Category.name).all()
    if request.method == 'POST':
        values, errors = parse_product_form(request.form, current=product)
        if errors:
            flash(' '.join(errors), 'danger')
            return render_template('seller/edit_product.html', product=product, categories=categories), 400
        changed = any(getattr(product, field) != value for field, value in values.items())
        if changed:
            apply_product_form(product, values)
            product.is_approved = False
        db.session.commit()
        flash(
            'Товар обновлён и отправлен на повторную модерацию' if changed else 'Изменений нет',
            'success' if changed else 'info',
        )
        return redirect(url_for('seller.products'))
    return render_template('seller/edit_product.html', product=product, categories=categories)


@seller_bp.route('/products/delete/<int:product_id>', methods=['POST'])
@login_required
@seller_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, seller_id=current_user.id).first_or_404()
    product.is_active = False
    db.session.commit()
    flash('Товар снят с продажи', 'info')
    return redirect(url_for('seller.products'))


@seller_bp.route('/become-seller', methods=['POST'])
@login_required
def become_seller():
    if current_user.role == 'user':
        current_user.role = 'seller'
        db.session.commit()
        flash('Поздравляем! Теперь вы можете продавать товары.', 'success')
        return redirect(url_for('seller.dashboard'))
    return redirect(url_for('seller.dashboard' if current_user.is_seller else 'main.index'))
