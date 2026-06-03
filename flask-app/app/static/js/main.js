document.addEventListener('DOMContentLoaded', function () {

    document.querySelectorAll('.fav-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var productId = btn.dataset.productId;
            fetch('/favorite/toggle/' + productId, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            }).then(function (r) {
                return r.json();
            }).then(function (data) {
                var icon = btn.querySelector('i');
                if (data.status === 'added') {
                    icon.className = 'bi bi-heart-fill';
                    btn.classList.add('active');
                } else {
                    icon.className = 'bi bi-heart';
                    btn.classList.remove('active');
                }
            }).catch(function () {
                window.location.href = '/auth/login';
            });
        });
    });

    document.querySelectorAll('.add-to-cart-ajax').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var productId = btn.dataset.productId;
            var form = new FormData();
            form.append('quantity', '1');
            fetch('/cart/add/' + productId, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: form
            }).then(function (r) {
                return r.json();
            }).then(function (data) {
                if (data.status === 'ok') {
                    var badge = document.querySelector('.cart-badge');
                    if (badge) badge.textContent = data.count;
                    btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Добавлено';
                    btn.classList.add('btn-success');
                    btn.classList.remove('btn-wb');
                    setTimeout(function () {
                        btn.innerHTML = '<i class="bi bi-cart-plus me-1"></i>В корзину';
                        btn.classList.remove('btn-success');
                        btn.classList.add('btn-wb');
                    }, 2000);
                }
            }).catch(function () {
                window.location.href = '/auth/login';
            });
        });
    });

    document.querySelectorAll('.star-rating input').forEach(function (input) {
        input.addEventListener('change', function () {
            document.querySelectorAll('.star-rating label').forEach(function (lbl, idx, arr) {
                lbl.style.color = idx < parseInt(input.value) ? '#ffc107' : '#ddd';
            });
        });
    });

    var tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltips.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });
});
