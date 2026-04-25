from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import CategoriaProduto, SubcategoriaProduto
def get_empresa_da_sessao(request):
    from .models import Empresa
    empresa_id = request.session.get('empresa_id')
    if not empresa_id:
        return None
    try:
        return Empresa.objects.get(id=empresa_id)
    except Empresa.DoesNotExist:
        return None

@login_required
@require_POST
def criar_categoria_ajax(request):
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    nome = request.POST.get('nome', '').strip()
    descricao = request.POST.get('descricao', '')
    subcategorias = request.POST.getlist('subcategorias[]')

    if not nome:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nome da categoria é obrigatório.'})

    categoria, created = CategoriaProduto.objects.get_or_create(
        empresa=empresa,
        nome=nome,
        defaults={'descricao': descricao}
    )
    if not created:
        return JsonResponse({'status': 'erro', 'mensagem': f'Já existe uma categoria com o nome "{nome}".'})

    subcats_criadas = []
    for subcat_nome in subcategorias:
        subcat_nome = subcat_nome.strip()
        if subcat_nome:
            subcat, _ = SubcategoriaProduto.objects.get_or_create(
                empresa=empresa,
                categoria=categoria,
                nome=subcat_nome
            )
            subcats_criadas.append({'id': subcat.id, 'nome': subcat.nome})

    return JsonResponse({
        'status': 'ok',
        'categoria': {'id': categoria.id, 'nome': categoria.nome},
        'subcategorias': subcats_criadas
    })


@login_required
@require_POST
def excluir_categoria_ajax(request, id):
    empresa = get_empresa_da_sessao(request)
    try:
        categoria = CategoriaProduto.objects.get(id=id, empresa=empresa)
        categoria.delete()
        return JsonResponse({'status': 'ok'})
    except CategoriaProduto.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Categoria não encontrada.'})


@login_required
@require_POST
def criar_subcategoria_ajax(request):
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    categoria_id = request.POST.get('categoria_id')
    nome = request.POST.get('nome', '').strip()

    if not nome or not categoria_id:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nome e categoria são obrigatórios.'})

    try:
        categoria = CategoriaProduto.objects.get(id=categoria_id, empresa=empresa)
    except CategoriaProduto.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Categoria não encontrada.'})

    subcat, created = SubcategoriaProduto.objects.get_or_create(
        empresa=empresa,
        categoria=categoria,
        nome=nome
    )
    if not created:
        return JsonResponse({'status': 'erro', 'mensagem': f'Subcategoria "{nome}" já existe nesta categoria.'})

    return JsonResponse({'status': 'ok', 'subcategoria': {'id': subcat.id, 'nome': subcat.nome}})


@login_required
def editar_categoria_ajax(request, id):
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})
    try:
        categoria = CategoriaProduto.objects.get(id=id, empresa=empresa)
    except CategoriaProduto.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Categoria não encontrada.'})

    if request.method == 'GET':
        subcats = list(categoria.subcategorias.values('id', 'nome'))
        return JsonResponse({
            'status': 'ok',
            'id': categoria.id,
            'nome': categoria.nome,
            'descricao': categoria.descricao or '',
            'subcategorias': subcats
        })

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        descricao = request.POST.get('descricao', '')
        if not nome:
            return JsonResponse({'status': 'erro', 'mensagem': 'Nome é obrigatório.'})
        categoria.nome = nome
        categoria.descricao = descricao
        categoria.save()

        # Sincroniza subcategorias: mantém apenas as enviadas
        nomes_enviados = [s.strip() for s in request.POST.getlist('subcategorias[]') if s.strip()]
        # Apaga as que não estão mais na lista
        categoria.subcategorias.exclude(nome__in=nomes_enviados).delete()
        # Cria as novas que ainda não existem
        for subcat_nome in nomes_enviados:
            SubcategoriaProduto.objects.get_or_create(
                empresa=empresa,
                categoria=categoria,
                nome=subcat_nome
            )
        return JsonResponse({'status': 'ok'})
