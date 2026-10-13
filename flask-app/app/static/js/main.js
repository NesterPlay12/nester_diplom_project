document.addEventListener('DOMContentLoaded', function () {
    var appBasePath = document.querySelector('meta[name="app-base-path"]')?.content || '';
    var csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    var appUrl = function (path) { return appBasePath + path; };
    var postJson = function (path, body) {
        return fetch(appUrl(path), {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken
            },
            body: body
        }).then(function (response) {
            if (response.redirected) {
                window.location.href = response.url;
                throw new Error('Требуется вход в аккаунт');
            }
            return response.json().then(function (data) {
                if (!response.ok) throw new Error(data.message || 'Не удалось выполнить запрос');
                return data;
            });
        });
    };

    document.querySelectorAll('.fav-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var productId = btn.dataset.productId;
            postJson('/favorite/toggle/' + productId).then(function (data) {
                var icon = btn.querySelector('i');
                if (data.status === 'added') {
                    icon.className = 'bi bi-heart-fill';
                    btn.classList.add('active');
                } else {
                    icon.className = 'bi bi-heart';
                    btn.classList.remove('active');
                }
            }).catch(function (error) {
                if (!error.message.includes('вход в аккаунт')) alert(error.message);
                if (error.message.includes('вход в аккаунт')) window.location.href = appUrl('/auth/login');
            });
        });
    });

    document.querySelectorAll('.add-to-cart-ajax').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var productId = btn.dataset.productId;
            var form = new FormData();
            form.append('quantity', '1');
            postJson('/cart/add/' + productId, form).then(function (data) {
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
            }).catch(function (error) {
                if (!error.message.includes('вход в аккаунт')) alert(error.message);
                if (error.message.includes('вход в аккаунт')) window.location.href = appUrl('/auth/login');
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
