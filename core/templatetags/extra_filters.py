from django import template
register = template.Library()

@register.filter
def br_number(value, decimal_places=2):
    try:
        decimal_places = int(decimal_places)
        formatted = f"{float(value):,.{decimal_places}f}"
        # Converter de US para BR: 1,234.56 → 1.234,56
        formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
        return formatted
    except (ValueError, TypeError):
        return value

@register.filter
def get_materia_prima_subcats(categorias_list):
    result = []
    for cat in categorias_list:
        if cat.nome.strip().lower() in ['matéria prima', 'materia prima']:
            result.extend(cat.subcategorias.all())
    return result
