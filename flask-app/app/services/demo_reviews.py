"""Clearly labelled presentation-only examples; never stored as customer reviews.

Fill the gap between imported catalogue counters and real Review rows, keeping
existing ratings untouched. Generate only the requested page, not thousands of
database users, orders or reviews.
"""
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class ReviewEntry:
    author: str
    rating: int
    text: str
    created_at: object = None
    is_demo: bool = False
    sample_number: int = 0


@dataclass(frozen=True)
class ReviewPage:
    items: list
    total: int
    real_count: int
    demo_count: int
    page: int
    pages: int
    per_page: int

    @property
    def first(self):
        return (self.page - 1) * self.per_page + 1 if self.total else 0

    @property
    def last(self):
        return min(self.page * self.per_page, self.total)


_NAMES = (
    'Анна', 'Михаил', 'Елена', 'Александр', 'Ольга', 'Дмитрий',
    'Мария', 'Сергей', 'Наталья', 'Андрей', 'Ирина', 'Павел',
    'Татьяна', 'Роман', 'Анастасия', 'Виктор', 'Юлия', 'Алексей',
    'Екатерина', 'Иван', 'Валерия', 'Никита', 'Светлана', 'Артём',
)
_INITIALS = 'АБВГДЕКЛМНОПРСТФ'
_OPENINGS = (
    'Первое впечатление положительное.', 'В целом впечатления хорошие.',
    'Качество исполнения понравилось.', 'Внешний вид соответствует описанию.',
    'Товар выглядит аккуратно.', 'Приятное сочетание цены и качества.',
    'Сравнение с описанием не вызвало вопросов.', 'Есть свои плюсы и небольшие нюансы.',
    'Ожидания в основном оправдались.', 'Удобный вариант для повседневного использования.',
    'Детали хорошо продуманы.', 'Общее впечатление скорее положительное.',
)
_DETAILS = {
    'phone': (
        'Экран яркий, мелкий текст хорошо читается.',
        'Камера особенно хорошо снимает при дневном свете.',
        'Меню работает плавно, приложения запускаются быстро.',
        'Корпус удобный, но защитный чехол будет полезен.',
        'Настройки понятные, к расположению кнопок легко привыкнуть.',
        'Для длительной работы на высокой яркости нужен запас заряда.',
    ),
    'laptop': (
        'Клавиатура удобная, ход клавиш приятный.',
        'Экран подходит для работы с текстом и таблицами.',
        'Небольшой вес удобен для поездок.',
        'Для привычной периферии может понадобиться переходник.',
        'Тачпад отзывчивый, жесты работают предсказуемо.',
        'Для обычных рабочих задач производительности достаточно.',
    ),
    'headphones': (
        'Амбушюры мягкие, посадка комфортная.',
        'Звук сбалансированный, бас можно настроить эквалайзером.',
        'Шумоподавление удобно в транспорте.',
        'При долгом ношении посадка может ощущаться плотной.',
        'Складной чехол пригодится в дороге.',
        'К управлению жестами нужно немного привыкнуть.',
    ),
    'clothes': (
        'Материал приятный на ощупь.',
        'Швы аккуратные, заметных неровностей нет.',
        'Перед выбором размера полезно свериться с таблицей.',
        'Оттенок немного зависит от освещения.',
        'Фасон легко сочетать с базовыми вещами.',
        'Вещь выглядит аккуратно, посадка зависит от фигуры.',
    ),
    'shoes': (
        'Подошва хорошо сгибается, колодка удобная.',
        'Для выбора размера лучше измерить длину стопы.',
        'Материал верха лёгкий.',
        'Шнуровка позволяет подобрать плотность посадки.',
        'Цвет вживую может немного отличаться от фотографии.',
        'Для повседневных прогулок вариант выглядит удачным.',
    ),
    'care': (
        'Упаковка аккуратная, обозначения хорошо читаются.',
        'Текстура лёгкая и удобно распределяется.',
        'Аромат заметен, это стоит учитывать при выборе.',
        'Состав лучше проверить с учётом особенностей кожи.',
        'Формат набора удобен для знакомства со средствами.',
        'Расход зависит от привычного способа нанесения.',
    ),
    'band': (
        'Экран хорошо читается в помещении.',
        'Ремешок удобно регулируется по руке.',
        'Меню понятное, основные функции находятся быстро.',
        'Уведомления помогают реже доставать телефон.',
        'Показания активности подходят для общего наблюдения, не для медицинских выводов.',
        'Настройки яркости заметно влияют на расход заряда.',
    ),
    'toy': (
        'Инструкция понятная, этапы сборки хорошо показаны.',
        'Детали соединяются плотно.',
        'Готовая модель выглядит интересно.',
        'Мелкие элементы удобно раскладывать заранее.',
        'При выборе стоит учитывать возрастную маркировку.',
        'Набор подходит для спокойного совместного занятия.',
    ),
    'book': (
        'Печать чёткая, текст удобно читать.',
        'Оформление обложек хорошо смотрится на полке.',
        'Бумага достаточно плотная.',
        'Переплёт аккуратный.',
        'Комплект занимает заметное место на полке.',
        'Перед выбором полезно проверить состав издания и перевод.',
    ),
    'generic': (
        'Основные характеристики соответствуют описанию.',
        'Детали выглядят аккуратно.',
        'Размеры лучше заранее сопоставить со своими задачами.',
        'Комплектацию полезно проверить по карточке товара.',
        'Материалы оставляют хорошее впечатление.',
        'Дизайн лаконичный и удобный.',
    ),
}
_ENDINGS = (
    'Особенно понравилось внимание к деталям.',
    'Существенных замечаний к внешнему виду нет.',
    'Перед выбором советую внимательно прочитать характеристики.',
    'Для своих задач выглядит подходящим вариантом.',
    'В целом удачное решение, если подходят характеристики.',
    'Важно учитывать личные предпочтения и условия использования.',
    'Из мелочей: хотелось бы больше вариантов оформления.',
    'Окончательный выбор зависит от привычек и ожиданий.',
    'Соотношение возможностей и стоимости выглядит разумным.',
    'Впечатления хорошие, хотя некоторые нюансы индивидуальны.',
    'Небольшие особенности не мешают общему впечатлению.',
    'Описание помогает заранее понять, чего ожидать.',
)


def _category(name):
    name = name.casefold()
    for words, category in (
        (('iphone', 'samsung', 'redmi', 'смартфон'), 'phone'),
        (('macbook', 'ноутбук'), 'laptop'),
        (('sony', 'наушник'), 'headphones'),
        (('платье', 'джинс'), 'clothes'),
        (('кроссов', 'обувь'), 'shoes'),
        (('уход', 'крем'), 'care'),
        (('браслет', 'band'), 'band'),
        (('lego', 'конструктор'), 'toy'),
        (('поттер', 'книг', 'собрание'), 'book'),
    ):
        if any(word in name for word in words):
            return category
    return 'generic'


def _example(product, index):
    rng = random.Random(f'wm-demo:{product.id}:{product.name}:{index}')
    average = float(product.rating or 0)
    if not math.isfinite(average):
        average = 4
    # Stable illustrative stars near the existing grade, without recalculating it.
    average = min(5, max(1, average))
    rating = min(5, max(1, int(average) + (rng.random() < average % 1)))
    details = _DETAILS[_category(product.name)]
    # A coprime stride walks the sentence combinations without repeating a text
    # until the combination space is exhausted. Each product has a stable order.
    combinations = len(_OPENINGS) * len(details) * (len(details) - 1) * len(_ENDINGS)
    code = (index * 37 + product.id * 101) % combinations
    opening = _OPENINGS[code % len(_OPENINGS)]
    code //= len(_OPENINGS)
    detail_index = code % len(details)
    detail = details[detail_index]
    code //= len(details)
    second_index = code % (len(details) - 1)
    if second_index >= detail_index:
        second_index += 1
    second_detail = details[second_index]
    code //= len(details) - 1
    ending = _ENDINGS[code]
    # Some entries demonstrate rating without a comment, as in the real form.
    text = '' if index % 9 == 8 else f'{opening} {detail} {second_detail} {ending}'
    return ReviewEntry(
        author=f'{rng.choice(_NAMES)} {rng.choice(_INITIALS)}.',
        rating=rating, text=text, is_demo=True, sample_number=index + 1,
    )


def review_page(product, query, page=1, per_page=20):
    """Keep real reviews first; fill only the missing part of the stored counter."""
    real_count = query.count()
    total = max(real_count, int(product.review_count or 0), 0)
    pages = max(1, (total + per_page - 1) // per_page)
    if page < 1 or page > pages:
        raise ValueError('Review page does not exist')
    offset = (page - 1) * per_page
    end = min(offset + per_page, total)
    items = []
    if offset < real_count:
        items.extend(
            ReviewEntry(
                author=review.user.username, rating=review.rating,
                text=review.text or '', created_at=review.created_at,
            )
            for review in query.offset(offset).limit(min(per_page, real_count - offset)).all()
        )
    for position in range(max(offset, real_count), end):
        items.append(_example(product, position - real_count))
    return ReviewPage(
        items=items, total=total, real_count=real_count,
        demo_count=total - real_count, page=page, pages=pages, per_page=per_page,
    )
