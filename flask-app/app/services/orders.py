from sqlalchemy import update

from ..models import Order, OrderItem, Product, db


ORDER_TRANSITIONS = {
    'pending': {'confirmed', 'cancelled'},
    'confirmed': {'processing', 'cancelled'},
    'processing': {'shipped', 'cancelled'},
    'shipped': {'delivered'},
    'delivered': set(),
    'cancelled': set(),
}


def transition_order(order, new_status):
    """Apply a valid order transition and restore stock exactly once on cancellation."""
    current_status = order.status
    if new_status not in ORDER_TRANSITIONS.get(current_status, set()):
        return False

    updated = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == current_status)
        .values(status=new_status),
        execution_options={'synchronize_session': False},
    )
    if updated.rowcount != 1:
        db.session.expire(order, ['status'])
        return False

    if new_status == 'cancelled':
        quantities = {}
        for item in order.items:
            if item.product_id:
                quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        for product_id, quantity in quantities.items():
            db.session.execute(
                update(Product)
                .where(Product.id == product_id)
                .values(stock=Product.stock + quantity)
            )

    db.session.expire(order, ['status'])
    return True
