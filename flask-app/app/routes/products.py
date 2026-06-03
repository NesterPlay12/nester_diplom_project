from flask import Blueprint, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import db, Product, Review, Favorite

products_bp = Blueprint('products', __name__)


@products_bp.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)
    existing = Review.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        flash('Вы уже оставили отзыв на этот товар', 'warning')
        return redirect(url_for('main.product_detail', product_id=product_id))

    rating = request.form.get('rating', type=int)
    text = request.form.get('text', '').strip()
    if not rating or rating < 1 or rating > 5:
        flash('Укажите оценку от 1 до 5', 'danger')
        return redirect(url_for('main.product_detail', product_id=product_id))

    review = Review(user_id=current_user.id, product_id=product_id, rating=rating, text=text)
    db.session.add(review)

    reviews = Review.query.filter_by(product_id=product_id).all()
    all_ratings = [r.rating for r in reviews] + [rating]
    product.rating = round(sum(all_ratings) / len(all_ratings), 1)
    product.review_count = len(all_ratings)

    db.session.commit()
    flash('Отзыв добавлен. Спасибо!', 'success')
    return redirect(url_for('main.product_detail', product_id=product_id))


@products_bp.route('/favorite/toggle/<int:product_id>', methods=['POST'])
@login_required
def toggle_favorite(product_id):
    existing = Favorite.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'status': 'removed'})
    fav = Favorite(user_id=current_user.id, product_id=product_id)
    db.session.add(fav)
    db.session.commit()
    return jsonify({'status': 'added'})
