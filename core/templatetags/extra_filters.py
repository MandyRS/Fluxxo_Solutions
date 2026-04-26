from django import template
register = template.Library()

@register.filter
def get_materia_prima_subcats(categorias_list):
    result = []
    for cat in categorias_list:
        if cat.nome.strip().lower() in ['matéria prima', 'materia prima']:
            result.extend(cat.subcategorias.all())
    return result
