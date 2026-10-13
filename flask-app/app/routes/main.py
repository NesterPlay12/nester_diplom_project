from flask import Blueprint, render_template, request, flash
from flask_login import current_user
from ..models import db, Product, Category, Review, Order, OrderItem
from ..services.catalog import filter_by_price, parse_price_filters, sort_products

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    categories = Category.query.filter_by(parent_id=None).all()
    featured = Product.query.filter_by(is_active=True, is_approved=True).order_by(Product.rating.desc()).limit(12).all()
    new_arrivals = Product.query.filter_by(is_active=True, is_approved=True).order_by(Product.created_at.desc()).limit(12).all()
    return render_template('index.html', categories=categories, featured=featured, new_arrivals=new_arrivals)


@main_bp.route('/category/<slug>')
def category(slug):
    cat = Category.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'popular')
    min_price, max_price, price_errors = parse_price_filters(request.args)
    if price_errors:
        flash(' '.join(price_errors), 'warning')

    child_ids = [c.id for c in cat.children] + [cat.id]
    query = Product.query.filter(
        Product.category_id.in_(child_ids),
        Product.is_active.is_(True),
        Product.is_approved.is_(True),
    )
    query = filter_by_price(query, min_price, max_price)
    query = sort_products(query, sort)

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    all_categories = Category.query.filter_by(parent_id=None).all()
    return render_template('category.html', category=cat, products=pagination.items,
                           pagination=pagination, sort=sort, all_categories=all_categories,
                           min_price=min_price, max_price=max_price)


@main_bp.route('/search')
def search():
    q = request.args.get('q', '').strip()[:120]
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'popular')
    cat_id = request.args.get('category', type=int)
    min_price, max_price, price_errors = parse_price_filters(request.args)
    if price_errors:
        flash(' '.join(price_errors), 'warning')

    query = Product.query.filter(Product.is_active.is_(True), Product.is_approved.is_(True))

    if q:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{q}%'),
                Product.description.ilike(f'%{q}%'),
                Product.brand.ilike(f'%{q}%')
            )
        )
    if cat_id:
        query = query.filter(Product.category_id == cat_id)
    query = filter_by_price(query, min_price, max_price)
    query = sort_products(query, sort)

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    categories = Category.query.filter_by(parent_id=None).all()
    return render_template('search.html', products=pagination.items, pagination=pagination,
                           q=q, sort=sort, categories=categories, cat_id=cat_id,
                           min_price=min_price, max_price=max_price)


@main_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True, is_approved=True).first_or_404()
    related = Product.query.filter(
        Product.category_id == product.category_id,
        Product.id != product.id,
        Product.is_active.is_(True),
        Product.is_approved.is_(True)
    ).order_by(Product.rating.desc(), Product.id.desc()).limit(8).all()
    reviews = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc()).all()
    can_review = False
    has_review = False
    if current_user.is_authenticated:
        has_review = Review.query.filter_by(
            product_id=product_id,
            user_id=current_user.id,
        ).first() is not None
        can_review = not has_review and db.session.query(OrderItem.id).join(
            Order, Order.id == OrderItem.order_id
        ).filter(
            Order.user_id == current_user.id,
            Order.status == 'delivered',
            OrderItem.product_id == product_id,
        ).first() is not None
    return render_template(
        'product.html',
        product=product,
        related=related,
        reviews=reviews,
        can_review=can_review,
        has_review=has_review,
    )
