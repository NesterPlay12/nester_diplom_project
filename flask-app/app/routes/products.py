from flask import Blueprint, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..models import db, Product, Review, Favorite, Order, OrderItem
from ..services.review_totals import add_rating

products_bp = Blueprint('products', __name__)


@products_bp.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    product = db.first_or_404(
        db.select(Product).where(Product.id == product_id).with_for_update()
    )
    purchased = (
        db.session.query(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.user_id == current_user.id,
            Order.status == 'delivered',
            OrderItem.product_id == product_id,
        )
        .first()
    )
    if not purchased:
        flash('Оставить отзыв можно после получения товара', 'warning')
        return redirect(url_for('main.product_detail', product_id=product_id))

    existing = Review.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        flash('Вы уже оставили отзыв на этот товар', 'warning')
        return redirect(url_for('main.product_detail', product_id=product_id))

    rating = request.form.get('rating', type=int)
    text = request.form.get('text', '').strip()
    if rating is None or rating < 1 or rating > 5:
        flash('Укажите оценку от 1 до 5', 'danger')
        return redirect(url_for('main.product_detail', product_id=product_id))
    if len(text) > 5000:
        flash('Текст отзыва слишком длинный', 'danger')
        return redirect(url_for('main.product_detail', product_id=product_id))

    review = Review(user_id=current_user.id, product_id=product_id, rating=rating, text=text)
    db.session.add(review)
    try:
        db.session.flush()
        add_rating(product, rating)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Вы уже оставили отзыв на этот товар', 'warning')
        return redirect(url_for('main.product_detail', product_id=product_id))
    flash('Отзыв добавлен. Спасибо!', 'success')
    return redirect(url_for('main.product_detail', product_id=product_id))


@products_bp.route('/favorite/toggle/<int:product_id>', methods=['POST'])
@login_required
def toggle_favorite(product_id):
    db.get_or_404(Product, product_id)
    existing = Favorite.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'status': 'removed'})
    fav = Favorite(user_id=current_user.id, product_id=product_id)
    db.session.add(fav)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'status': 'added'})
    return jsonify({'status': 'added'})
