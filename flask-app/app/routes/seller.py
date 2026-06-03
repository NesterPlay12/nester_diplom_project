from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from functools import wraps
from ..models import db, Product, Category, Order, OrderItem

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
    from ..models import OrderItem
    sold_items = OrderItem.query.filter(OrderItem.product_id.in_(product_ids)).all() if product_ids else []
    revenue = sum(i.price * i.quantity for i in sold_items)
    active_count = sum(1 for p in products if p.is_active and p.is_approved)
    pending_count = sum(1 for p in products if not p.is_approved)
    return render_template('seller/dashboard.html', products=products, revenue=revenue,
                           active_count=active_count, pending_count=pending_count,
                           sold_count=len(sold_items))


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
    categories = Category.query.all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', type=float)
        old_price = request.form.get('old_price', type=float)
        brand = request.form.get('brand', '').strip()
        category_id = request.form.get('category_id', type=int)
        stock = request.form.get('stock', 0, type=int)
        image_url = request.form.get('image_url', '').strip()

        if not name or not price or not category_id:
            flash('Заполните обязательные поля: название, цена, категория', 'danger')
            return render_template('seller/add_product.html', categories=categories)

        product = Product(
            name=name, description=description, price=price,
            old_price=old_price if old_price else None,
            brand=brand, category_id=category_id,
            seller_id=current_user.id, stock=stock,
            image_url=image_url or 'https://via.placeholder.com/400x400?text=Фото',
            is_active=True, is_approved=False
        )
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
    categories = Category.query.all()
    if request.method == 'POST':
        product.name = request.form.get('name', product.name).strip()
        product.description = request.form.get('description', '').strip()
        product.price = request.form.get('price', product.price, type=float)
        old_price = request.form.get('old_price', type=float)
        product.old_price = old_price if old_price else None
        product.brand = request.form.get('brand', '').strip()
        product.category_id = request.form.get('category_id', product.category_id, type=int)
        product.stock = request.form.get('stock', 0, type=int)
        image_url = request.form.get('image_url', '').strip()
        if image_url:
            product.image_url = image_url
        product.is_approved = False
        db.session.commit()
        flash('Товар обновлён и отправлен на повторную модерацию', 'success')
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
