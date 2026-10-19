"""Keep imported rating aggregates when real reviews are added or removed.

The stored count/mean includes legacy catalogue ratings without Review rows.
Never rebuild it solely from Review. Callers lock the product and commit the
aggregate together with the actual review. Round only when displaying the mean.
"""


def add_rating(product, rating):
    count = product.review_count or 0
    total = (product.rating or 0) * count
    product.review_count = count + 1
    product.rating = (total + rating) / product.review_count


def remove_rating(product, rating):
    count = product.review_count or 0
    if count <= 1:
        product.review_count = 0
        product.rating = 0
    else:
        product.review_count = count - 1
        product.rating = ((product.rating or 0) * count - rating) / product.review_count
