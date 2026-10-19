from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class DemoPickupPoint(db.Model):
    """Persistent overrides/additions to the address-linked demo catalogue."""
    __tablename__ = 'demo_pickup_points'
    id = db.Column(db.String(64), primary_key=True)
    city = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    address = db.Column(db.String(500), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    work_time = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (
        db.UniqueConstraint('city', 'address', name='uq_demo_pickup_city_address'),
        db.CheckConstraint('lat >= -90 AND lat <= 90', name='ck_demo_pickup_lat'),
        db.CheckConstraint('lng >= -180 AND lng <= 180', name='ck_demo_pickup_lng'),
    )


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    has_local_password = db.Column(db.Boolean, nullable=False, default=True)
    google_id = db.Column(db.String(100), unique=True)
    role = db.Column(db.String(20), default='user')
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    avatar_url = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    orders = db.relationship('Order', backref='user', lazy=True)
    reviews = db.relationship('Review', backref='user', lazy=True)
    cart_items = db.relationship('CartItem', backref='user', lazy=True)
    favorites = db.relationship('Favorite', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role in ('admin', 'moderator')

    @property
    def is_seller(self):
        return self.role in ('seller', 'admin')

    def __repr__(self):
        return f'<User {self.username}>'


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    icon = db.Column(db.String(50), default='📦')
    image_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    children = db.relationship('Category', backref=db.backref('parent', remote_side=[id]), lazy=True)
    products = db.relationship('Product', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    old_price = db.Column(db.Float)
    brand = db.Column(db.String(100))
    sku = db.Column(db.String(50))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(255))
    color_options = db.Column(db.Text, default='')
    size_options = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    seller = db.relationship('User', foreign_keys=[seller_id], backref='products')
    reviews = db.relationship('Review', backref='product', lazy=True, cascade='all, delete-orphan')
    cart_items = db.relationship('CartItem', backref='product', lazy=True, cascade='all, delete-orphan')
    favorites = db.relationship('Favorite', backref='product', lazy=True, cascade='all, delete-orphan')

    @property
    def discount_percent(self):
        if self.old_price and self.old_price > self.price:
            return int((1 - self.price / self.old_price) * 100)
        return 0

    @property
    def available_stock(self):
        return max(self.stock or 0, 0)

    @property
    def colors(self):
        return [value.strip() for value in (self.color_options or '').split(',') if value.strip()]

    @property
    def sizes(self):
        return [value.strip() for value in (self.size_options or '').split(',') if value.strip()]

    def __repr__(self):
        return f'<Product {self.name}>'


class CartItem(db.Model):
    __tablename__ = 'cart_items'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    # Legacy NULLs are preserved by lossless imports; new rows default to ''.
    selected_color = db.Column(db.String(80), default='')
    selected_size = db.Column(db.String(40), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'product_id', 'selected_color', 'selected_size',
            name='uq_cart_item_variant',
        ),
        db.Index(
            'uq_cart_item_normalized_variant',
            'user_id', 'product_id',
            db.func.coalesce(selected_color, ''),
            db.func.coalesce(selected_size, ''),
            unique=True,
        ),
    )


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(30), default='pending')
    total = db.Column(db.Float, nullable=False)
    address = db.Column(db.Text, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default='cash_on_delivery')
    phone = db.Column(db.String(20))
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    STATUS_LABELS = {
        'pending': 'Ожидает подтверждения',
        'confirmed': 'Подтверждён',
        'processing': 'В обработке',
        'shipped': 'Отправлен',
        'delivered': 'Доставлен',
        'cancelled': 'Отменён',
    }
    PAYMENT_LABELS = {
        'cash_on_delivery': 'Оплата при получении',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        colors = {
            'pending': 'warning',
            'confirmed': 'info',
            'processing': 'primary',
            'shipped': 'info',
            'delivered': 'success',
            'cancelled': 'danger',
        }
        return colors.get(self.status, 'secondary')

    @property
    def payment_label(self):
        return self.PAYMENT_LABELS.get(self.payment_method, 'Не указан')


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(255), nullable=False)
    product_image = db.Column(db.String(255))
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    selected_color = db.Column(db.String(80))
    selected_size = db.Column(db.String(40))

    product = db.relationship('Product')

    @property
    def subtotal(self):
        return self.quantity * self.price


class Review(db.Model):
    __tablename__ = 'reviews'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),)


class Favorite(db.Model):
    __tablename__ = 'favorites'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),)
