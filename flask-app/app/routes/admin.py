from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from ..models import db, User, Product, Category, Order, Review
from ..services.orders import ORDER_TRANSITIONS, transition_order
from ..services.product_input import apply_product_form, parse_product_form

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    stats = {
        'users': User.query.count(),
        'products': Product.query.count(),
        'orders': Order.query.count(),
        'categories': Category.query.count(),
        'pending_products': Product.query.filter_by(is_approved=False, is_active=True).count(),
        'revenue': db.session.query(db.func.sum(Order.total)).filter(Order.status != 'cancelled').scalar() or 0,
    }
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html', stats=stats, recent_orders=recent_orders, recent_users=recent_users)


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '')
    query = User.query
    if search:
        query = query.filter(db.or_(User.username.ilike(f'%{search}%'), User.email.ilike(f'%{search}%')))
    if role_filter:
        query = query.filter(User.role == role_filter)
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', pagination=pagination, search=search, role_filter=role_filter)


@admin_bp.route('/users/<int:user_id>/role', methods=['POST'])
@login_required
@admin_required
def change_role(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Нельзя изменить собственную роль', 'warning')
        return redirect(url_for('admin.users'))
    new_role = request.form.get('role')
    if new_role in ('user', 'seller', 'moderator', 'admin'):
        if current_user.role != 'admin' and (
            new_role == 'admin' or user.role == 'admin'
        ):
            flash('Только администратор может управлять ролью администратора', 'danger')
            return redirect(url_for('admin.users'))
        user.role = new_role
        db.session.commit()
        flash(f'Роль пользователя {user.username} изменена на {new_role}', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Нельзя заблокировать себя', 'warning')
        return redirect(url_for('admin.users'))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'разблокирован' if user.is_active else 'заблокирован'
    flash(f'Пользователь {user.username} {status}', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/products')
@login_required
@admin_required
def products():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')
    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    if status == 'pending':
        query = query.filter_by(is_approved=False, is_active=True)
    elif status == 'approved':
        query = query.filter_by(is_approved=True, is_active=True)
    elif status == 'inactive':
        query = query.filter_by(is_active=False)
    pagination = query.order_by(Product.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/products.html', pagination=pagination, search=search, status=status)


@admin_bp.route('/products/<int:product_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_product(product_id):
    product = db.get_or_404(Product, product_id)
    product.is_approved = True
    product.is_active = True
    db.session.commit()
    flash(f'Товар "{product.name}" одобрен', 'success')
    return redirect(url_for('admin.products', status='pending'))


@admin_bp.route('/products/<int:product_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_product(product_id):
    product = db.get_or_404(Product, product_id)
    product.is_approved = False
    product.is_active = False
    db.session.commit()
    flash(f'Товар "{product.name}" отклонён', 'warning')
    return redirect(url_for('admin.products', status='pending'))


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    product = db.get_or_404(Product, product_id)
    # Keep order-history foreign keys and snapshots intact.
    product.is_active = False
    db.session.commit()
    flash('Товар снят с продажи; история заказов сохранена', 'info')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = db.get_or_404(Product, product_id)
    categories = Category.query.order_by(Category.parent_id, Category.name).all()
    if request.method == 'POST':
        values, errors = parse_product_form(request.form, current=product)
        if errors:
            flash(' '.join(errors), 'danger')
            return render_template('admin/edit_product.html', product=product, categories=categories), 400
        apply_product_form(product, values)
        db.session.commit()
        flash(f'Товар "{product.name}" обновлён', 'success')
        return redirect(url_for('admin.products'))
    return render_template('admin/edit_product.html', product=product, categories=categories)


@admin_bp.route('/orders')
@login_required
@admin_required
def orders():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    query = Order.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    pagination = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/orders.html', pagination=pagination, status_filter=status_filter)


@admin_bp.route('/orders/<int:order_id>/status', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    order = db.get_or_404(Order, order_id)
    new_status = request.form.get('status')
    if transition_order(order, new_status):
        db.session.commit()
        flash(f'Статус заказа #{order.id} обновлён', 'success')
    else:
        flash('Недопустимый переход статуса заказа', 'warning')
    return redirect(url_for('admin.orders'))


@admin_bp.route('/categories')
@login_required
@admin_required
def categories():
    cats = Category.query.order_by(Category.parent_id, Category.name).all()
    roots = [cat for cat in cats if not cat.parent_id]
    return render_template('admin/categories.html', categories=cats, root_categories=roots)


@admin_bp.route('/categories/add', methods=['POST'])
@login_required
@admin_required
def add_category():
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip().lower()
    icon = request.form.get('icon', '📦').strip()
    parent_id = request.form.get('parent_id', type=int)
    if not name or len(name) > 100 or not slug or len(slug) > 100:
        flash('Укажите название (до 100 символов) и корректный slug', 'danger')
        return redirect(url_for('admin.categories'))
    if not all(part and part.isascii() and part.isalnum() for part in slug.split('-')):
        flash('Slug может содержать только латинские буквы, цифры и дефисы', 'danger')
        return redirect(url_for('admin.categories'))
    if Category.query.filter_by(slug=slug).first():
        flash('Такой slug уже существует', 'danger')
        return redirect(url_for('admin.categories'))
    if parent_id and not db.session.get(Category, parent_id):
        flash('Выбранная родительская категория не найдена', 'danger')
        return redirect(url_for('admin.categories'))
    cat = Category(name=name, slug=slug, icon=icon, parent_id=parent_id or None)
    db.session.add(cat)
    db.session.commit()
    flash(f'Категория "{name}" добавлена', 'success')
    return redirect(url_for('admin.categories'))


@admin_bp.route('/categories/<int:cat_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(cat_id):
    cat = db.get_or_404(Category, cat_id)
    if cat.children or cat.products:
        flash('Нельзя удалить категорию с подкатегориями или товарами', 'danger')
        return redirect(url_for('admin.categories'))
    db.session.delete(cat)
    db.session.commit()
    flash('Категория удалена', 'info')
    return redirect(url_for('admin.categories'))


@admin_bp.route('/reviews')
@login_required
@admin_required
def reviews():
    page = request.args.get('page', 1, type=int)
    pagination = Review.query.order_by(Review.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/reviews.html', pagination=pagination)


@admin_bp.route('/reviews/<int:review_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_review(review_id):
    review = db.get_or_404(Review, review_id)
    product = review.product
    db.session.delete(review)
    db.session.flush()
    remaining = Review.query.filter_by(product_id=product.id).all()
    product.review_count = len(remaining)
    product.rating = round(sum(item.rating for item in remaining) / len(remaining), 1) if remaining else 0
    db.session.commit()
    flash('Отзыв удалён', 'info')
    return redirect(url_for('admin.reviews'))
