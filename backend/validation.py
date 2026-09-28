"""Shared API contracts. No implicit string, number or boolean coercion."""


def object_value(value, label='Данные', allowed=None):
    if not isinstance(value, dict):
        raise ValueError(f'{label}: ожидается объект.')
    if allowed is not None and set(value) - set(allowed):
        raise ValueError(f'{label}: есть неподдерживаемые поля.')
    return value


def list_value(value, label='Список'):
    if not isinstance(value, list):
        raise ValueError(f'{label}: ожидается список.')
    return value


def text_value(value, label, maximum=200, empty=True):
    if not isinstance(value, str):
        raise ValueError(f'{label}: ожидается текст.')
    value = value.strip()
    if (not empty and not value) or len(value) > maximum:
        raise ValueError(f'{label}: допустимо от {0 if empty else 1} до {maximum} символов.')
    return value


def integer(value, label='Срок', minimum=0, maximum=100000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}: укажите целое число от {minimum} до {maximum}.')
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f'{label}: ожидается true или false.')
    return value


def dependencies(value):
    return [text_value(item, 'Зависимость', 128, empty=False)
            for item in list_value(value, 'Зависимости')]
