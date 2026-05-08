import json
import io

import pandas as pd
from datetime import date as dt_date, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import (
    Sum, F, FloatField, Q,
    Prefetch, OuterRef, Subquery, DecimalField,
)
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from .models import (
    Empresa, UserEmpresa, Cliente, Produto, Servico,
    Orcamento, ItemOrcamento,
    Banco, LancamentoBancario,
    ItemEstoque, MovimentacaoEstoque,
    Fornecedor, EntradaComercial, ItemEntradaComercial,
    SubcategoriaProduto, ProdutoMateriaPrima, CategoriaProduto,
)
from .forms import ItemOrcamentoForm, BancoForm, LancamentoBancarioForm, MovimentacaoEstoqueForm


# -----------------------------
# INDEX
# -----------------------------
def index(request):
    """Página inicial pública da aplicação."""
    return render(request, 'index.html')

# -----------------------------
# LOGIN / LOGOUT
# -----------------------------
def login_view(request):
    """Autentica o usuário e redireciona para seleção de empresa."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('core:selecionar_empresa')
        else:
            messages.error(request, "Usuário ou senha incorretos")

    return render(request, 'login.html')

@login_required
def logout_view(request):
    """Encerra a sessão do usuário e redireciona para a página inicial."""
    logout(request)
    return redirect('core:index')


# -----------------------------
# SELECIONAR EMPRESA
# -----------------------------
@login_required
def selecionar_empresa(request):
    """Lista as empresas vinculadas ao usuário e define a empresa ativa na sessão."""
    # Busca as empresas vinculadas ao usuário logado
    empresas_vinculadas = UserEmpresa.objects.filter(user=request.user)

    if request.method == 'POST':
        empresa_id = request.POST.get('empresa_id')
        if empresa_id:
            empresa_permitida = UserEmpresa.objects.filter(
                user=request.user,
                empresa_id=empresa_id,
            ).exists()
            if empresa_permitida:
                request.session['empresa_id'] = int(empresa_id)
                return redirect('core:dashboard')
            messages.error(request, 'Empresa inválida para o usuário logado.')

    return render(request, 'selecionar_empresa.html', {
        'empresas': empresas_vinculadas  # 👈 nome da variável usada no template
    })


# -----------------------------
# FUNÇÃO AUXILIAR
# -----------------------------

# Busca empresa pela sessão
def get_empresa_da_sessao(request):
    """Helper: retorna a Empresa da sessão validando vínculo com o usuário logado."""
    if not request.user.is_authenticated:
        return None
    empresa_id = request.session.get('empresa_id')
    if not empresa_id:
        return None

    empresa_permitida = UserEmpresa.objects.filter(
        user=request.user,
        empresa_id=empresa_id,
    ).exists()
    if not empresa_permitida:
        return None

    try:
        return Empresa.objects.get(id=empresa_id)
    except Empresa.DoesNotExist:
        return None


# -----------------------------
# DASHBOARD
# -----------------------------

@login_required
def dashboard(request):
    """Dashboard principal com KPIs financeiros, de estoque e comerciais da empresa selecionada."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return render(request, "erro.html", {"mensagem": "Nenhuma empresa associada."})

    # Contadores básicos
    clientes = empresa.cliente_set.count()
    produtos = empresa.produto_set.count()
    servicos = empresa.servico_set.count()
    orcamentos = empresa.orcamento_set.all()

    # Valor total orçamentos
    orcamentos_valor_total = (
        ItemOrcamento.objects.filter(orcamento__empresa=empresa)
        .aggregate(total=Sum(F("quantidade") * F("preco_unitario"), output_field=FloatField()))
    )["total"] or 0

    # Alerta de orçamentos com previsão de entrega próxima
    hoje = timezone.now().date()
    limite_alerta = hoje + timedelta(days=3)
    alerta_orcamentos = orcamentos.filter(previsao_entrega__range=[hoje, limite_alerta])

    # Produtos com estoque crítico — mesma lógica do template de estoque: quantidade <= 10
    itens_estoque = ItemEstoque.objects.filter(empresa=empresa)
    total_estoque_itens = itens_estoque.count()
    produtos_criticos = ItemEstoque.objects.filter(
        empresa=empresa,
        quantidade__lte=10
    ).order_by('quantidade')

    # Produtos com maior estoque (top 6)
    produtos_maior_estoque = ItemEstoque.objects.filter(
        empresa=empresa, quantidade__gt=0
    ).order_by('-quantidade')[:6]

    # Top produtos que mais saíram (MovimentacaoEstoque tipo saida)
    top_saidas = (
        MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='saida')
        .values('item__id', 'item__nome', 'item__unidade')
        .annotate(total=Sum('quantidade'))
        .order_by('-total')[:6]
    )
    top_entradas = (
        MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='entrada')
        .values('item__id', 'item__nome', 'item__unidade')
        .annotate(total=Sum('quantidade'))
        .order_by('-total')[:6]
    )

    # Orçamentos recentes (últimos 5)
    orcamentos_recentes = orcamentos.order_by('-criado_em')[:5]

    # Entradas recentes (últimas 5)
    entradas_recentes = EntradaComercial.objects.filter(empresa=empresa).order_by('-data')[:5]

    # Saldo bancário total
    bancos = Banco.objects.filter(empresa=empresa)
    saldo_bancario_total = 0
    for banco in bancos:
        saldo = float(banco.saldo_inicial)
        for lanc in banco.lancamentos.all():
            if lanc.tipo == 'entrada':
                saldo += float(lanc.valor)
            else:
                saldo -= float(lanc.valor)
        saldo_bancario_total += saldo

    # Receitas e despesas do mês atual
    mes_atual = hoje.month
    ano_atual = hoje.year
    lancamentos_mes = LancamentoBancario.objects.filter(
        banco__empresa=empresa, data__month=mes_atual, data__year=ano_atual
    )
    receitas_mes = float(lancamentos_mes.filter(tipo='entrada').aggregate(
        t=Sum('valor', output_field=FloatField()))['t'] or 0)
    despesas_mes = float(lancamentos_mes.filter(tipo='saida').aggregate(
        t=Sum('valor', output_field=FloatField()))['t'] or 0)
    saldo_mes = receitas_mes - despesas_mes

    # Orçamentos do mês atual
    orcamentos_mes_atual = orcamentos.filter(criado_em__month=mes_atual, criado_em__year=ano_atual)
    orcamentos_mes_count = orcamentos_mes_atual.count()
    orcamentos_valor_mes_atual = float(
        ItemOrcamento.objects.filter(
            orcamento__empresa=empresa,
            orcamento__criado_em__month=mes_atual,
            orcamento__criado_em__year=ano_atual,
        ).aggregate(total=Sum(F("quantidade") * F("preco_unitario"), output_field=FloatField()))["total"] or 0
    )

    # Valor total entradas comerciais do mês
    entradas_mes = EntradaComercial.objects.filter(
        empresa=empresa, data__month=mes_atual, data__year=ano_atual
    )
    itens_entradas_mes = ItemEntradaComercial.objects.filter(entrada__in=entradas_mes)
    valor_entradas_mes = sum(float(i.quantidade) * float(i.preco_unitario) for i in itens_entradas_mes)
    entradas_mes_count = entradas_mes.count()
    fornecedores_mes_count = entradas_mes.exclude(fornecedor=None).values('fornecedor').distinct().count()

    # Gráfico: orçamentos por mês
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    orcamentos_mes = []
    orcamentos_valor_mes = []
    for i in range(1, 13):
        orcs_mes = orcamentos.filter(criado_em__month=i, criado_em__year=ano_atual)
        orcamentos_mes.append(orcs_mes.count())
        valor_mes = (
            ItemOrcamento.objects.filter(
                orcamento__empresa=empresa,
                orcamento__criado_em__month=i,
                orcamento__criado_em__year=ano_atual,
            ).aggregate(total=Sum(F("quantidade") * F("preco_unitario"), output_field=FloatField()))
        )["total"] or 0
        orcamentos_valor_mes.append(float(valor_mes))

    context = {
        "empresa": empresa,
        "clientes": clientes,
        "produtos": produtos,
        "servicos": servicos,
        "orcamentos": orcamentos.count(),
        "orcamentos_valor_total": round(orcamentos_valor_total, 2),
        "alerta_orcamentos": alerta_orcamentos,
        "produtos_maior_estoque": produtos_maior_estoque,
        "top_saidas": list(top_saidas),
        "top_entradas": list(top_entradas),
        "orcamentos_recentes": orcamentos_recentes,
        "entradas_recentes": entradas_recentes,
        "produtos_criticos": produtos_criticos,
        "total_estoque_itens": total_estoque_itens,
        "saldo_bancario_total": round(saldo_bancario_total, 2),
        "saldo_mes": round(saldo_mes, 2),
        "receitas_mes": round(receitas_mes, 2),
        "despesas_mes": round(despesas_mes, 2),
        "orcamentos_mes_count": orcamentos_mes_count,
        "orcamentos_valor_mes_atual": round(orcamentos_valor_mes_atual, 2),
        "valor_entradas_mes": round(valor_entradas_mes, 2),
        "entradas_mes_count": entradas_mes_count,
        "fornecedores_mes_count": fornecedores_mes_count,
        "hoje": hoje,
        "meses": json.dumps(meses),
        "orcamentos_mes": json.dumps(orcamentos_mes),
        "orcamentos_valor_mes": json.dumps(orcamentos_valor_mes),
    }

    return render(request, "dashboard.html", context)




# -----------------------------
# FLUXO BANCÁRIO
# -----------------------------

@login_required
def fluxo_bancario_dashboard(request):
    """Exibe extrato bancário com saldo e movimentações filtradas por banco e período."""
    empresa = get_empresa_da_sessao(request)
    bancos = Banco.objects.filter(empresa=empresa)
    banco_id = request.GET.get('banco')
    data_inicial = request.GET.get('data_inicial', '')
    data_final = request.GET.get('data_final', '')
    banco_selecionado = None
    lancamentos = []
    saldo_anterior = 0
    saldo_atual = 0
    total_entradas = 0
    total_saidas = 0

    if banco_id:
        banco_selecionado = get_object_or_404(Banco, id=banco_id, empresa=empresa)
        todos = banco_selecionado.lancamentos.order_by('data', 'id')

        # Saldo anterior = saldo_inicial + lançamentos anteriores ao período
        saldo_anterior = float(banco_selecionado.saldo_inicial)
        if data_inicial:
            for l in todos.filter(data__lt=data_inicial):
                saldo_anterior += float(l.valor) if l.tipo == 'entrada' else -float(l.valor)
        else:
            saldo_anterior = float(banco_selecionado.saldo_inicial)

        # Lançamentos do período
        lancamentos = todos
        if data_inicial:
            lancamentos = lancamentos.filter(data__gte=data_inicial)
        if data_final:
            lancamentos = lancamentos.filter(data__lte=data_final)

        for l in lancamentos:
            if l.tipo == 'entrada':
                total_entradas += float(l.valor)
            else:
                total_saidas += float(l.valor)

        saldo_atual = saldo_anterior + total_entradas - total_saidas

        # Se não há filtro de data, saldo_anterior é o saldo_inicial configurado
        if not data_inicial:
            saldo_anterior = float(banco_selecionado.saldo_inicial)

    return render(request, 'fluxo_bancario.html', {
        'bancos': bancos,
        'banco_selecionado': banco_selecionado,
        'lancamentos': lancamentos,
        'saldo_anterior': round(saldo_anterior, 2),
        'saldo_atual': round(saldo_atual, 2),
        'total_entradas': round(total_entradas, 2),
        'total_saidas': round(total_saidas, 2),
        'data_inicial': data_inicial,
        'data_final': data_final,
    })


@login_required
def novo_lancamento_bancario(request):
    """Cria um novo lançamento bancário via formulário."""
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST':
        form = LancamentoBancarioForm(request.POST)
        if form.is_valid():
            lanc = form.save(commit=False)
            banco = lanc.banco
            if banco.empresa != empresa:
                return HttpResponse('Banco inválido', status=403)
            lanc.criado_por = request.user
            lanc.save()
            return redirect(f"/fluxo-bancario/?banco={banco.id}")
    else:
        form = LancamentoBancarioForm()
    return render(request, 'novo_lancamento_bancario.html', {'form': form})


@login_required
def editar_lancamento_bancario(request, id):
    """Edita um lançamento bancário existente pertencente à empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    lancamento = get_object_or_404(LancamentoBancario, id=id, banco__empresa=empresa)
    if request.method == 'POST':
        form = LancamentoBancarioForm(request.POST, instance=lancamento)
        if form.is_valid():
            lanc = form.save(commit=False)
            if lanc.banco.empresa != empresa:
                return HttpResponse('Banco inválido', status=403)
            lanc.save()
            return redirect(f"/fluxo-bancario/?banco={lanc.banco.id}")
    else:
        form = LancamentoBancarioForm(instance=lancamento)
    return render(request, 'novo_lancamento_bancario.html', {
        'form': form,
        'editando': True,
        'lancamento': lancamento,
    })


@login_required
def excluir_lancamento_bancario(request, id):
    """Exclui um lançamento bancário via POST."""
    if request.method != 'POST':
        return HttpResponse('Método não permitido', status=405)
    empresa = get_empresa_da_sessao(request)
    lancamento = get_object_or_404(LancamentoBancario, id=id, banco__empresa=empresa)
    banco_id = lancamento.banco.id
    lancamento.delete()
    return redirect(f"/fluxo-bancario/?banco={banco_id}")


@login_required
def importar_lancamentos_excel(request):
    """Importa lançamentos bancários em lote a partir de uma planilha Excel."""
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST' and request.FILES.get('arquivo'):
        arquivo = request.FILES['arquivo']
        df = pd.read_excel(arquivo)
        for _, row in df.iterrows():
            banco = Banco.objects.get(id=row['banco_id'], empresa=empresa)
            LancamentoBancario.objects.create(
                banco=banco,
                data=row['data'],
                descricao=row['descricao'],
                valor=row['valor'],
                tipo=row['tipo'],
                classificacao=row['classificacao'],
                criado_por=request.user
            )
        return redirect(f"/fluxo-bancario/?banco={banco.id}")
    return render(request, 'importar_lancamentos_excel.html')


@login_required
def baixar_planilha_exemplo(request):
    """Gera e baixa uma planilha Excel de exemplo para importação de lançamentos bancários."""
    output = io.BytesIO()
    df = pd.DataFrame({
        'banco_id': [1],
        'data': ['2026-04-18'],
        'descricao': ['Exemplo de lançamento'],
        'valor': [100.00],
        'tipo': ['entrada'],
        'classificacao': ['investimento'],
    })
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=exemplo_lancamentos.xlsx'
    return response



# --------------------------------------------------------
# CLIENTES
# --------------------------------------------------------

@login_required
@require_POST
def criar_cliente_ajax(request):
    """API POST: cria um novo cliente para a empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    cliente = Cliente.objects.create(
        empresa=empresa,
        razao_social=request.POST.get('razao_social') or '',
        nome_fantasia=request.POST.get('nome_fantasia') or '',
        cpf_cnpj=request.POST.get('cpf_cnpj') or '',
        telefone=request.POST.get('telefone') or '',
        email=request.POST.get('email') or '',
        endereco=request.POST.get('endereco') or '',
        cidade_uf=request.POST.get('cidade_uf') or '',
        cep=request.POST.get('cep') or '',
    )

    return JsonResponse({
        'status': 'ok',
        'cliente': {
            'id': cliente.id,
            'razao_social': cliente.razao_social,
            'nome_fantasia': cliente.nome_fantasia,
            'cpf_cnpj': cliente.cpf_cnpj,
            'telefone': cliente.telefone,
        }
    })

@login_required
@require_POST
def excluir_cliente(request, id):
    """API POST: exclui um cliente da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST':
        try:
            cliente = Cliente.objects.get(id=id, empresa=empresa)
            cliente.delete()
            return JsonResponse({'status': 'ok', 'mensagem': 'Cliente excluído com sucesso'})
        except Cliente.DoesNotExist:
            return JsonResponse({'status': 'erro', 'mensagem': 'Cliente não encontrado'})
    return JsonResponse({'status': 'erro', 'mensagem': 'Método inválido'})

@login_required
def editar_cliente(request, id):
    """API GET/POST: retorna ou atualiza dados de um cliente da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    cliente = Cliente.objects.get(id=id, empresa=empresa)
    if request.method == 'GET':
        # retornar os dados em JSON
        return JsonResponse({
            'id': cliente.id,
            'razao_social': cliente.razao_social,
            'nome_fantasia': cliente.nome_fantasia,
            'cpf_cnpj': cliente.cpf_cnpj,
            'telefone': cliente.telefone,
            'email': cliente.email,
            'endereco': cliente.endereco,
            'cidade_uf': cliente.cidade_uf,
            'cep': cliente.cep,
        })
    elif request.method == 'POST':
        # atualizar os dados
        cliente.razao_social = request.POST.get('razao_social') or ''
        cliente.nome_fantasia = request.POST.get('nome_fantasia') or ''
        cliente.cpf_cnpj = request.POST.get('cpf_cnpj') or ''
        cliente.telefone = request.POST.get('telefone') or ''
        cliente.email = request.POST.get('email') or ''
        cliente.endereco = request.POST.get('endereco') or ''
        cliente.cidade_uf = request.POST.get('cidade_uf') or ''
        cliente.cep = request.POST.get('cep') or ''
        cliente.save()
        return JsonResponse({'status': 'ok', 'cliente': {
            'id': cliente.id,
            'razao_social': cliente.razao_social,
            'nome_fantasia': cliente.nome_fantasia,
            'cpf_cnpj': cliente.cpf_cnpj,
            'telefone': cliente.telefone,
        }})

#--------------------------------------------------------

@login_required
@require_POST
def criar_produto_ajax(request):
    """API POST: cria um novo produto e seu respectivo item de estoque inicial."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    def parse_decimal_br(value):
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return value
        value = str(value).replace('.', '').replace(',', '.')
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def eh_categoria_materia_prima(subcategoria_obj):
        if not subcategoria_obj or not getattr(subcategoria_obj, 'categoria', None):
            return False
        nome = (subcategoria_obj.categoria.nome or '').strip().lower()
        return nome in ('matéria prima', 'materia prima')


    preco = parse_decimal_br(request.POST.get('preco'))
    preco_unitario = parse_decimal_br(request.POST.get('preco_unitario'))
    estoque_inicial = parse_decimal_br(request.POST.get('estoque_inicial'))
    peso = parse_decimal_br(request.POST.get('peso'))

    subcat_id = request.POST.get('subcategoria')
    subcategoria = None
    if subcat_id:
        try:
            subcategoria = SubcategoriaProduto.objects.get(id=subcat_id, empresa=empresa)
        except SubcategoriaProduto.DoesNotExist:
            subcategoria = None

    estoque_inicial_item = estoque_inicial
    if eh_categoria_materia_prima(subcategoria):
        estoque_inicial_item = estoque_inicial * peso

    produto = Produto.objects.create(
        empresa=empresa,
        codigo=request.POST.get('codigo'),
        nome=request.POST.get('nome'),
        descricao=request.POST.get('descricao'),
        preco=preco,
        peso=peso,
        unidade=request.POST.get('unidade') or 'un',
        preco_unitario=preco_unitario,
        categoria=request.POST.get('categoria', 'produto'),
        subcategoria=subcategoria,
    )

    # Cria o item de estoque vinculado ao produto
    item_estoque = ItemEstoque.objects.create(
        empresa=empresa,
        produto=produto,
        nome=produto.nome,
        codigo=produto.codigo,
        quantidade=estoque_inicial_item,
        unidade=produto.unidade,
    )
    # Se estoque inicial > 0, registra movimentação de entrada
    if estoque_inicial_item > 0:
        MovimentacaoEstoque.objects.create(
            item=item_estoque,
            tipo='entrada',
            quantidade=estoque_inicial_item,
            data=dt_date.today(),
            observacao='Estoque inicial',
            criado_por=request.user,
        )

    # Salvar ficha técnica de matéria-prima
    ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa).delete()
    mp_keys = [k for k in request.POST if k.startswith('mp_produto_id_')]
    for key in mp_keys:
        idx = key.replace('mp_produto_id_', '')
        mp_id = request.POST.get(key, '').strip()
        mp_qtd = request.POST.get(f'mp_quantidade_{idx}', '0').strip()
        mp_unidade = request.POST.get(f'mp_unidade_{idx}', 'un').strip()
        if not mp_id:
            continue
        try:
            mp_qtd = float(mp_qtd)
        except ValueError:
            continue
        if mp_qtd <= 0:
            continue
        try:
            mp_produto = Produto.objects.get(id=mp_id, empresa=empresa)
        except Produto.DoesNotExist:
            continue
        ProdutoMateriaPrima.objects.update_or_create(
            empresa=empresa,
            produto_final=produto,
            materia_prima=mp_produto,
            defaults={'quantidade': mp_qtd, 'unidade': mp_unidade},
        )

    return JsonResponse({
        'status': 'ok',
        'produto': {
            'id': produto.id,
            'nome': produto.nome,
            'descricao': produto.descricao,
            'unidade': produto.unidade,
            'preco_unitario': str(produto.preco_unitario),
            'categoria': produto.categoria,
            'estoque_inicial': estoque_inicial,
        }
    })


@login_required
@require_POST
def excluir_produto(request, id):
    """API POST: exclui um produto e seu item de estoque vinculado."""
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST':
        try:
            produto = Produto.objects.get(id=id, empresa=empresa)
            # Excluir ItemEstoque vinculado antes de excluir o produto
            ItemEstoque.objects.filter(produto=produto, empresa=empresa).delete()
            produto.delete()
            return JsonResponse({'status': 'ok', 'mensagem': 'Produto excluído com sucesso'})
        except Produto.DoesNotExist:
            return JsonResponse({'status': 'erro', 'mensagem': 'Produto não encontrado'})
    return JsonResponse({'status': 'erro', 'mensagem': 'Método inválido'})
@login_required
def editar_produto(request, id):
    """API GET/POST: retorna dados ou atualiza um produto da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    try:
        produto = Produto.objects.get(id=id, empresa=empresa)

        def eh_categoria_materia_prima(subcategoria_obj):
            if not subcategoria_obj or not getattr(subcategoria_obj, 'categoria', None):
                return False
            nome = (subcategoria_obj.categoria.nome or '').strip().lower()
            return nome in ('matéria prima', 'materia prima')

        if request.method == 'POST':
            def parse_decimal_br(value):
                if value is None:
                    return 0
                if isinstance(value, (int, float)):
                    return value
                value = str(value).replace('.', '').replace(',', '.')
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0

            produto.codigo = request.POST.get('codigo', produto.codigo)
            produto.nome = request.POST.get('nome', produto.nome)
            produto.descricao = request.POST.get('descricao', produto.descricao)
            produto.peso = parse_decimal_br(request.POST.get('peso', produto.peso))
            produto.unidade = request.POST.get('unidade', produto.unidade) or 'un'
            produto.preco_unitario = parse_decimal_br(request.POST.get('preco_unitario', produto.preco_unitario))
            produto.preco = parse_decimal_br(request.POST.get('preco', produto.preco))
            _cat_choices = ['produto', 'materia_prima', 'embalagem', 'tampa', 'rotulo']
            _cat_nova = request.POST.get('categoria', produto.categoria)
            if _cat_nova in _cat_choices:
                produto.categoria = _cat_nova
            produto.save()

            # Atualizar ficha técnica de matéria-prima
            ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa).delete()
            mp_keys = [k for k in request.POST if k.startswith('mp_produto_id_')]
            for key in mp_keys:
                idx = key.replace('mp_produto_id_', '')
                mp_id = request.POST.get(key, '').strip()
                mp_qtd = request.POST.get(f'mp_quantidade_{idx}', '0').strip()
                mp_unidade = request.POST.get(f'mp_unidade_{idx}', 'un').strip()
                if not mp_id:
                    continue
                try:
                    mp_qtd = float(mp_qtd)
                except ValueError:
                    continue
                if mp_qtd <= 0:
                    continue
                try:
                    mp_produto = Produto.objects.get(id=mp_id, empresa=empresa)
                except Produto.DoesNotExist:
                    continue
                ProdutoMateriaPrima.objects.update_or_create(
                    empresa=empresa,
                    produto_final=produto,
                    materia_prima=mp_produto,
                    defaults={'quantidade': mp_qtd, 'unidade': mp_unidade},
                )

            return JsonResponse({'status': 'ok', 'id': produto.id})
        # Buscar estoque inicial (quantidade do ItemEstoque vinculado)
        item_estoque = ItemEstoque.objects.filter(produto=produto, empresa=empresa).first()
        estoque_inicial = item_estoque.quantidade if item_estoque else 0
        if item_estoque and eh_categoria_materia_prima(produto.subcategoria) and float(produto.peso or 0) > 0:
            estoque_inicial = float(item_estoque.quantidade) / float(produto.peso)
        def format_real(valor):
            return ("%.2f" % float(valor)).replace('.', ',')
        # Buscar ficha técnica de matéria-prima
        materias_primas = []
        for mp in ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa):
            materias_primas.append({
                'id': mp.materia_prima.id,
                'nome': mp.materia_prima.nome,
                'quantidade': float(mp.quantidade),
                'unidade': mp.unidade,
            })
        data = {
            'id': produto.id,
            'codigo': produto.codigo,
            'nome': produto.nome,
            'descricao': produto.descricao,
            'peso': format_real(produto.peso),
            'unidade': produto.unidade,
            'preco_unitario': format_real(produto.preco_unitario),
            'categoria': produto.categoria,
            'estoque_inicial': format_real(estoque_inicial),
            'materias_primas': materias_primas,
        }
        return JsonResponse(data)
    except Produto.DoesNotExist:
        return JsonResponse({'erro': 'Produto não encontrado'}, status=404)

#--------------------------------------------------------

@login_required
@require_POST
def criar_servico_ajax(request):
    """API POST: cria um novo serviço para a empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    servico = Servico.objects.create(
        empresa=empresa,
        codigo=request.POST.get('codigo'),
        nome=request.POST.get('nome'),
        descricao=request.POST.get('descricao'),
        preco=request.POST.get('preco') or 0
    )

    return JsonResponse({
        'status': 'ok',
        'servico': {
            'id': servico.id,
            'nome': servico.nome,
            'descricao': servico.descricao,
            'preco': str(servico.preco),
        }
    })


    
@login_required
@require_POST
def editar_servico_ajax(request, id):
    """API GET: retorna dados de um serviço para preenchimento de modal de edição."""
    empresa = get_empresa_da_sessao(request)
    try:
        servico = Servico.objects.get(id=id, empresa=empresa)
        data = {
            'codigo': servico.codigo,
            'nome': servico.nome,
            'descricao': servico.descricao,
            'preco': str(servico.preco)
        }
        return JsonResponse(data)
    except Servico.DoesNotExist:
        return JsonResponse({'erro': 'Serviço não encontrado'}, status=404)
@login_required
def excluir_servico_ajax(request, id):
    """API POST: exclui um serviço da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST':
        try:
            servico = Servico.objects.get(id=id, empresa=empresa)
            servico.delete()
            return JsonResponse({'status': 'ok', 'mensagem': 'Serviço excluído com sucesso'})
        except Servico.DoesNotExist:
            return JsonResponse({'status': 'erro', 'mensagem': 'Serviço não encontrado'})
    return JsonResponse({'status': 'erro', 'mensagem': 'Método inválido'})


# --------------------------------------------------------
# ORÇAMENTOS
# --------------------------------------------------------

@login_required
def listar_orcamentos(request):
    """Exibe a lista de orçamentos da empresa com opção de criar novos."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return redirect('core:selecionar_empresa')

    orcamentos = Orcamento.objects.filter(empresa=empresa).order_by('-criado_em')
    clientes = Cliente.objects.filter(empresa=empresa)

    return render(request, 'orcamentos.html', {
        'orcamentos': orcamentos,
        'clientes': clientes,
    })


@login_required
@require_POST
def criar_orcamento(request):
    """API POST: cria um novo orçamento com itens e dá baixa no estoque dos produtos."""
    try:
        data = request.POST
        empresa = get_empresa_da_sessao(request)
        itens = json.loads(data.get('itens', '[]'))
        desconto = float(data.get('desconto', 0) or 0)


        orcamento = Orcamento.objects.create(
            empresa=empresa,
            usuario=request.user,
            cliente_id=data.get('cliente'),
            solicitante=data.get('solicitante'),
            previsao_entrega=data.get('previsao_entrega') or None,
            forma_pagamento=data.get('forma_pagamento'),
            vencimento=data.get('vencimento') or None,
            observacao=data.get('observacao'),
            responsavel=data.get('responsavel'),
            desconto=desconto,
        )

        total = 0
        for item in itens:
            tipo = item.get('tipo')
            qtd = float(item.get('quantidade') or 0)
            valor = float(item.get('valor_unitario') or 0)
            subtotal = qtd * valor
            total += subtotal

            if tipo == 'produto':
                ref = Produto.objects.filter(id=item.get('id_item'), empresa=empresa).first()
            else:
                ref = Servico.objects.filter(id=item.get('id_item'), empresa=empresa).first()

            ItemOrcamento.objects.create(
                orcamento=orcamento,
                produto=ref if tipo == 'produto' else None,
                servico=ref if tipo == 'servico' else None,
                quantidade=qtd,
                preco_unitario=valor
            )
            # Baixa no estoque para produtos
            if tipo == 'produto' and ref:
                item_est, _ = ItemEstoque.objects.get_or_create(
                    empresa=empresa, produto=ref,
                    defaults={'nome': ref.nome, 'quantidade': 0, 'unidade': ref.unidade}
                )
                item_est.quantidade = float(item_est.quantidade) - qtd
                item_est.save()
                MovimentacaoEstoque.objects.create(
                    item=item_est, tipo='saida', quantidade=qtd,
                    data=dt_date.today(),
                    observacao=f'Venda - Orca #{orcamento.numero}',
                    criado_por=request.user,
                )
                # Baixa automática nas matérias-primas (ficha técnica)
        ficha = ProdutoMateriaPrima.objects.filter(produto_final=ref, empresa=empresa)
        for mp in ficha:
                       item_mp = ItemEstoque.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
                       if item_mp:
                           consumo = float(mp.quantidade) * qtd
                           item_mp.quantidade = float(item_mp.quantidade) - consumo
                           item_mp.save()
                           MovimentacaoEstoque.objects.create(
                               item=item_mp, tipo='saida', quantidade=consumo,
                               data=dt_date.today(),
                               observacao=f'Consumo MP - Orca #{orcamento.numero} ({ref.nome})',
                               criado_por=request.user,
                           )

        orcamento.save()
        return JsonResponse({'status': 'ok'})

    except Exception as e:
        return JsonResponse({'status': 'erro', 'mensagem': str(e)})


@login_required
def obter_orcamento(request, orcamento_id):
    """Retorna os dados de um orçamento para edição (GET)."""
    if request.method != "GET":
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido'}, status=405)

    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    orc = get_object_or_404(Orcamento, id=orcamento_id, empresa=empresa)
    itens = ItemOrcamento.objects.filter(orcamento=orc).select_related(
        'produto', 'produto__subcategoria', 'produto__subcategoria__categoria',
        'servico', 'orcamento__cliente'
    )

    data = {
        'id': orc.id,
        'cliente_id': orc.cliente_id,
        'cliente_nome': orc.cliente.razao_social if orc.cliente else '',
        'cliente_nome_fantasia': orc.cliente.nome_fantasia if orc.cliente else '',
        'cliente_cpf_cnpj': orc.cliente.cpf_cnpj if orc.cliente else '',
        'cliente_email': orc.cliente.email if orc.cliente else '',
        'cliente_telefone': orc.cliente.telefone if orc.cliente else '',
        'cliente_endereco': orc.cliente.endereco if orc.cliente else '',
        'solicitante': orc.solicitante,
        'previsao_entrega': orc.previsao_entrega.strftime('%Y-%m-%d') if orc.previsao_entrega else '',
        'vencimento': orc.vencimento.strftime('%Y-%m-%d') if orc.vencimento else '',
        'forma_pagamento': orc.forma_pagamento,
        'responsavel': orc.responsavel,
        'desconto': float(orc.desconto or 0),
        'observacao': orc.observacao or '',
        'itens': [
            {
                'id_item': i.produto.id if i.produto else (i.servico.id if i.servico else None),
                'nome': i.produto.nome if i.produto else (i.servico.nome if i.servico else ''),
                'tipo': 'produto' if i.produto else 'servico',
                'quantidade': float(i.quantidade),
                'valor_unitario': float(i.preco_unitario),
                'categoria_id': (i.produto.subcategoria.categoria.id if i.produto and i.produto.subcategoria and i.produto.subcategoria.categoria else None),
                'subcategoria_id': (i.produto.subcategoria.id if i.produto and i.produto.subcategoria else None),
            }
            for i in itens
        ]
    }

    return JsonResponse({'status': 'ok', 'orcamento': data})


@login_required
@require_POST
def excluir_orcamento(request, orcamento_id):
    """API POST: exclui um orçamento da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    orcamento = get_object_or_404(
        Orcamento,
        id=orcamento_id,
        empresa=empresa,
    )
    try:
        orcamento.delete()
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "erro", "mensagem": str(e)})


@login_required
def imprimir_orcamento(request, orcamento_id):
    """Renderiza o template de impressão de um orçamento."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return redirect('core:selecionar_empresa')

    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa=empresa)
    itens = ItemOrcamento.objects.filter(orcamento=orcamento)

    return render(request, 'imprimir.html', {
        'orcamento': orcamento,
        'itens': itens,
    })

@login_required
def orcamento_detalhe_json(request, orcamento_id):
    """Retorna os dados do orçamento em JSON para o modal de edição."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa=empresa)
    itens = ItemOrcamento.objects.filter(orcamento=orcamento)

    data = {
        'id': orcamento.id,
        'cliente_id': orcamento.cliente.id if orcamento.cliente else None,
        'cliente_nome': orcamento.cliente.razao_social if orcamento.cliente else '',
        'solicitante': orcamento.solicitante,
        'previsao_entrega': orcamento.previsao_entrega.strftime('%Y-%m-%d') if orcamento.previsao_entrega else '',
        'vencimento': orcamento.vencimento.strftime('%Y-%m-%d') if orcamento.vencimento else '',
        'forma_pagamento': orcamento.forma_pagamento,
        'responsavel': orcamento.responsavel,
        'observacao': orcamento.observacao,
        'desconto': float(orcamento.desconto or 0),
        'itens': [
            {
                'id_item': i.produto.id if i.produto else (i.servico.id if i.servico else None),
                'tipo': 'produto' if i.produto else 'servico',
                'nome': i.produto.nome if i.produto else (i.servico.nome if i.servico else ''),
                'quantidade': float(i.quantidade),
                'valor_unitario': float(i.preco_unitario),
            }
            for i in itens
        ]
    }
    return JsonResponse({'status': 'ok', 'orcamento': data})


@login_required
@require_POST
def editar_orcamento(request, orcamento_id):
    """Salva alterações em um orçamento existente."""
    if request.method != "POST":
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido (use POST)'}, status=405)

    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa=empresa)
    try:
        data = request.POST
        itens = json.loads(data.get('itens', '[]'))
        desconto = float(data.get('desconto', 0) or 0)

        cliente_id = data.get('cliente')
        if cliente_id:
            cliente = Cliente.objects.filter(id=cliente_id, empresa=empresa).first()
            if not cliente:
                return JsonResponse({'status': 'erro', 'mensagem': 'Cliente inválido para a empresa.'}, status=400)
            orcamento.cliente = cliente
        else:
            orcamento.cliente = None

        orcamento.solicitante = data.get('solicitante')
        orcamento.previsao_entrega = data.get('previsao_entrega') or None
        orcamento.vencimento = data.get('vencimento') or None
        orcamento.forma_pagamento = data.get('forma_pagamento')
        orcamento.observacao = data.get('observacao')
        orcamento.responsavel = data.get('responsavel')
        orcamento.desconto = desconto

        # Remove os itens antigos
        ItemOrcamento.objects.filter(orcamento=orcamento).delete()

        total = 0
        for item in itens:
            tipo = item.get('tipo')
            qtd = float(item.get('quantidade') or 0)
            valor = float(item.get('valor_unitario') or 0)
            subtotal = qtd * valor
            total += subtotal

            if tipo == 'produto':
                ref = Produto.objects.filter(id=item.get('id_item'), empresa=empresa).first()
            else:
                ref = Servico.objects.filter(id=item.get('id_item'), empresa=empresa).first()

            ItemOrcamento.objects.create(
                orcamento=orcamento,
                produto=ref if tipo == 'produto' else None,
                servico=ref if tipo == 'servico' else None,
                quantidade=qtd,
                preco_unitario=valor
            )

        orcamento.save()
        return JsonResponse({'status': 'ok'})

    except Exception as e:
        return JsonResponse({'status': 'erro', 'mensagem': str(e)})




# --------------------------------------------------------
# ITENS DE ORÇAMENTO INDIVIDUAIS (caso use via AJAX)
# --------------------------------------------------------

@login_required
@require_POST
def adicionar_item(request, orcamento_id):
    """API POST: adiciona um item a um orçamento existente."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa=empresa)
    form = ItemOrcamentoForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.orcamento = orcamento
        item.save()
        return JsonResponse({'status': 'ok', 'item_id': item.id})
    return JsonResponse({'status': 'erro', 'erros': form.errors})


@login_required
@require_POST
def editar_item(request, item_id):
    """API POST: atualiza um item de orçamento existente."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa=empresa)
    form = ItemOrcamentoForm(request.POST, instance=item)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'erro', 'erros': form.errors})


@login_required
@require_POST
def excluir_item(request, item_id):
    """API POST: exclui um item de orçamento."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa=empresa)
    item.delete()
    return JsonResponse({'status': 'ok'})


@login_required
def detalhe_item(request, item_id):
    """API GET: retorna dados detalhados de um item de orçamento."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa=empresa)
    data = {
        'id': item.id,
        'produto': {'id': item.produto.id, 'nome': item.produto.nome} if item.produto else None,
        'servico': {'id': item.servico.id, 'nome': item.servico.nome} if item.servico else None,
        'quantidade': item.quantidade,
        'preco_unitario': float(item.preco_unitario),
    }
    return JsonResponse(data)


# --------------------------------------------------------
# AUTOCOMPLETES
# --------------------------------------------------------

def utf8_json_response(data):
    """Função auxiliar: retorna JsonResponse com suporte completo a UTF-8."""
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False})


@login_required
def autocomplete_cliente(request):
    """API GET: retorna sugestões de clientes para autocomplete (busca por nome ou id)."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse([], safe=False)

    term = request.GET.get('term', '')
    cliente_id = request.GET.get('id')

    clientes = Cliente.objects.filter(empresa=empresa)

    if cliente_id:
        clientes = clientes.filter(id=cliente_id)
    elif term:
        clientes = clientes.filter(razao_social__icontains=term)

    results = [
        {
            "id": c.id,
            "label": c.razao_social,
            "nome_fantasia": c.nome_fantasia,
            "cpf_cnpj": c.cpf_cnpj,
            "email": c.email,
            "telefone": c.telefone,
            "endereco": c.endereco,
        }
        for c in clientes
    ]
    return JsonResponse(results, safe=False)


@login_required
def autocomplete_produto_servico(request):
    """API GET: retorna produtos e serviços para autocomplete de orçamento."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse([], safe=False)

    termo = request.GET.get('term', '')
    produtos = Produto.objects.filter(empresa=empresa, nome__icontains=termo)
    servicos = Servico.objects.filter(empresa=empresa, nome__icontains=termo)

    resultados = []
    for p in produtos:
        resultados.append({
            "id": p.id,
            "label": p.nome,
            "tipo": "produto",
            "preco": float(p.preco)
        })
    for s in servicos:
        resultados.append({
            "id": s.id,
            "label": s.nome,
            "tipo": "servico",
            "preco": float(s.preco)
        })
    return JsonResponse(resultados, safe=False)


# --------------------------------------------------------
# OUTROS
# --------------------------------------------------------

@login_required
def configuracoes(request):
    """Página de configurações da empresa: clientes, produtos, serviços, bancos e fornecedores."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return redirect('core:index')

    def get_produtos_list(categoria):
        produtos = Produto.objects.filter(empresa=empresa, categoria=categoria)
        lista = []
        for p in produtos:
            item_estoque = ItemEstoque.objects.filter(produto=p, empresa=empresa).first()
            estoque_inicial = item_estoque.quantidade if item_estoque else 0
            lista.append({
                'id': p.id,
                'codigo': p.codigo,
                'nome': p.nome,
                'descricao': p.descricao,
                'peso': p.peso,
                'unidade': p.unidade,
                'preco_unitario': p.preco_unitario,
                'categoria': p.categoria,
                'estoque_inicial': estoque_inicial,
            })
        return lista

    # Anotação de estoque atual em cada produto
    estoque_subquery = Subquery(
        ItemEstoque.objects.filter(produto=OuterRef('pk'), empresa=empresa).values('quantidade')[:1],
        output_field=DecimalField()
    )
    produtos_com_estoque = Produto.objects.filter(empresa=empresa).annotate(
        estoque_atual=estoque_subquery
    )

    context = {
        'clientes_list': Cliente.objects.filter(empresa=empresa),
        'produtos_list': get_produtos_list('produto'),
        'materias_primas_list': get_produtos_list('materia_prima'),
        'embalagens_list': get_produtos_list('embalagem'),
        'tampas_list': get_produtos_list('tampa'),
        'rotulos_list': get_produtos_list('rotulo'),
        'servicos_list': Servico.objects.filter(empresa=empresa),
        'bancos_list': Banco.objects.filter(empresa=empresa),
        'fornecedores_list': Fornecedor.objects.filter(empresa=empresa),
        'categorias_list': CategoriaProduto.objects.filter(empresa=empresa)
            .prefetch_related(
                Prefetch(
                    'subcategorias',
                    queryset=SubcategoriaProduto.objects.filter(empresa=empresa).prefetch_related(
                        Prefetch('produtos', queryset=produtos_com_estoque)
                    )
                )
            ),
        'empresa': empresa,
    }
    return render(request, 'configuracoes.html', context)


@login_required
def suporte(request):
    """Página de suporte ao usuário com formulário de contato por módulo."""
    empresa = get_empresa_da_sessao(request)
    modulos = ['Financeiro', 'Dashboard', 'Orçamentos', 'Configurações', 'Relatórios', 'Outro']
    
    context = {
    'usuario': request.user,
    'modulos': modulos,
    'empresa': empresa,
}
    return render(request, 'suporte.html', context)

# -----------------------------
# BANCOS (AJAX)
# -----------------------------
@login_required
@require_POST
def criar_banco_ajax(request):
    """API POST: cria um novo banco para a empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})
    nome = request.POST.get('nome')
    agencia = request.POST.get('agencia')
    conta = request.POST.get('conta')
    saldo_inicial = request.POST.get('saldo_inicial') or 0
    banco = Banco.objects.create(
        empresa=empresa,
        nome=nome,
        agencia=agencia,
        conta=conta,
        saldo_inicial=saldo_inicial
    )
    return JsonResponse({'status': 'ok', 'banco': {
        'id': banco.id,
        'nome': banco.nome,
        'agencia': banco.agencia,
        'conta': banco.conta,
        'saldo_inicial': str(banco.saldo_inicial),
    }})

@login_required
@require_POST
def excluir_banco_ajax(request, id):
    """API POST: exclui um banco da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    try:
        banco = Banco.objects.get(id=id, empresa=empresa)
        banco.delete()
        return JsonResponse({'status': 'ok', 'mensagem': 'Banco excluído com sucesso'})
    except Banco.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Banco não encontrado'})

@login_required
@require_POST
def editar_banco_ajax(request, id):
    """API POST: edita os dados de um banco da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    try:
        banco = Banco.objects.get(id=id, empresa=empresa)
        banco.nome = request.POST.get('nome')
        banco.agencia = request.POST.get('agencia')
        banco.conta = request.POST.get('conta')
        banco.saldo_inicial = request.POST.get('saldo_inicial') or 0
        banco.save()
        return JsonResponse({'status': 'ok', 'banco': {
            'id': banco.id,
            'nome': banco.nome,
            'agencia': banco.agencia,
            'conta': banco.conta,
            'saldo_inicial': str(banco.saldo_inicial),
        }})
    except Banco.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Banco não encontrado'})

@login_required
def listar_bancos_ajax(request):
    """API GET: retorna a lista de bancos cadastrados para a empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    bancos = Banco.objects.filter(empresa=empresa)
    bancos_data = [
        {
            'id': b.id,
            'nome': b.nome,
            'agencia': b.agencia,
            'conta': b.conta,
            'saldo_inicial': str(b.saldo_inicial),
        } for b in bancos
    ]
    return JsonResponse({'status': 'ok', 'bancos': bancos_data})


# ============================================================
# ESTOQUE
# ============================================================

@login_required
def estoque(request):
    """Página de gestão de estoque: itens, movimentações e perdas."""
    empresa = get_empresa_da_sessao(request)
    itens = ItemEstoque.objects.filter(empresa=empresa, produto__isnull=False)
    movimentacoes = MovimentacaoEstoque.objects.filter(item__empresa=empresa).order_by('-data', '-id')[:100]
    perdas = MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='saida', observacao__icontains='perda').order_by('-data', '-id')[:50]
    valor_total_estoque = 0
    for item in itens:
        if item.produto and item.produto.preco_unitario:
            valor_total_estoque += float(item.quantidade) * float(item.produto.preco_unitario)
    categorias = CategoriaProduto.objects.filter(empresa=empresa).prefetch_related('subcategorias')
    categorias_json = json.dumps([
        {
            'id': cat.id,
            'nome': cat.nome,
            'subcategorias': [{'id': sub.id, 'nome': sub.nome} for sub in cat.subcategorias.all()]
        }
        for cat in categorias
    ])
    context = {
        'itens': itens,
        'movimentacoes': movimentacoes,
        'perdas': perdas,
        'valor_total_estoque': f"{valor_total_estoque:.2f}",
        'categorias_json': categorias_json,
    }
    return render(request, 'estoque.html', context)


def eh_produto_materia_prima(produto):
    """Retorna True se o produto pertence à categoria Matéria Prima."""
    if not produto or not produto.subcategoria or not produto.subcategoria.categoria:
        return False
    nome = (produto.subcategoria.categoria.nome or '').strip().lower()
    return nome in ('matéria prima', 'materia prima')


def quantidade_entrada_base_estoque(produto, quantidade):
    """Converte entrada em unidades para base de estoque (ml/g) quando for Matéria Prima."""
    try:
        qtd = float(quantidade)
    except (TypeError, ValueError):
        return 0
    if not eh_produto_materia_prima(produto):
        return qtd
    try:
        peso = float(produto.peso or 0)
    except (TypeError, ValueError):
        peso = 0
    if peso <= 0:
        return qtd
    return qtd * peso


@login_required
@require_POST
def criar_item_estoque(request):
    """API POST: cria ou atualiza um item de estoque; registra movimentação e baixa matérias-primas."""
    empresa = get_empresa_da_sessao(request)
    produto_id = request.POST.get('produto_id')
    produto = None
    if produto_id:
        try:
            produto = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            produto = None
    quantidade_nova = float(request.POST.get('quantidade', 0))
    tipo_mov = request.POST.get('tipo', 'entrada')  # 'entrada' ou 'saida'
    if produto:
        quantidade_mov = quantidade_entrada_base_estoque(produto, quantidade_nova) if tipo_mov == 'entrada' else quantidade_nova
        item = ItemEstoque.objects.filter(empresa=empresa, produto=produto).first()
        if item:
            # Já existe, soma ou subtrai do estoque atual
            if tipo_mov == 'entrada':
                item.quantidade = float(item.quantidade) + quantidade_mov
            elif tipo_mov == 'saida':
                item.quantidade = float(item.quantidade) - quantidade_nova
                # Dar baixa nas matérias-primas vinculadas (ficha técnica)
                ficha = ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa)
                for mp in ficha:
                    item_mp = ItemEstoque.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
                    if item_mp:
                        item_mp.quantidade = float(item_mp.quantidade) - (float(mp.quantidade) * quantidade_nova)
                        item_mp.save()
                        # Registrar movimentação de saída da matéria-prima
                        MovimentacaoEstoque.objects.create(
                            item=item_mp,
                            tipo='saida',
                            quantidade=(float(mp.quantidade) * quantidade_nova),
                            data=dt_date.today(),
                            observacao=f'Consumo para produção de {produto.nome}',
                            criado_por=request.user,
                        )
            item.save()
            # Registrar movimentação
            MovimentacaoEstoque.objects.create(
                item=item,
                tipo=tipo_mov,
                quantidade=quantidade_mov,
                data=dt_date.today(),
                observacao='Movimentação manual',
                criado_por=request.user,
            )
        else:
            # Não existe, cria novo
            item = ItemEstoque.objects.create(
                empresa=empresa,
                produto=produto,
                nome=request.POST.get('nome', ''),
                codigo=request.POST.get('codigo', ''),
                quantidade=quantidade_mov if tipo_mov == 'entrada' else -quantidade_nova,
                unidade=request.POST.get('unidade', 'un'),
                preco_custo=request.POST.get('preco_custo', 0),
                estoque_minimo=request.POST.get('estoque_minimo', 0),
            )
            # Registrar movimentação
            MovimentacaoEstoque.objects.create(
                item=item,
                tipo=tipo_mov,
                quantidade=quantidade_mov,
                data=dt_date.today(),
                observacao='Estoque inicial' if tipo_mov == 'entrada' else 'Saída inicial',
                criado_por=request.user,
            )
    else:
        # Sem produto vinculado
        item = ItemEstoque.objects.create(
            empresa=empresa,
            produto=None,
            nome=request.POST.get('nome', ''),
            codigo=request.POST.get('codigo', ''),
            quantidade=quantidade_nova if tipo_mov == 'entrada' else -quantidade_nova,
            unidade=request.POST.get('unidade', 'un'),
            preco_custo=request.POST.get('preco_custo', 0),
            estoque_minimo=request.POST.get('estoque_minimo', 0),
        )
        # Registrar movimentação
        MovimentacaoEstoque.objects.create(
            item=item,
            tipo=tipo_mov,
            quantidade=quantidade_nova,
            data=dt_date.today(),
            observacao='Estoque inicial' if tipo_mov == 'entrada' else 'Saída inicial',
            criado_por=request.user,
        )
    return JsonResponse({'status': 'ok', 'id': item.id, 'nome': item.nome})


@login_required
def editar_item_estoque(request, id):
    """API GET/POST: retorna ou atualiza dados de um item de estoque."""
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    if request.method == 'GET':
        return JsonResponse({
            'id': item.id,
            'nome': item.nome,
            'codigo': item.codigo,
            'quantidade': str(item.quantidade),
            'unidade': item.unidade,
            'preco_custo': str(item.preco_custo),
            'estoque_minimo': str(item.estoque_minimo),
        })
    elif request.method == 'POST':
        item.nome = request.POST.get('nome', item.nome)
        item.codigo = request.POST.get('codigo', item.codigo)
        item.quantidade = request.POST.get('quantidade', item.quantidade)
        item.unidade = request.POST.get('unidade', item.unidade)
        item.preco_custo = request.POST.get('preco_custo', item.preco_custo)
        item.estoque_minimo = request.POST.get('estoque_minimo', item.estoque_minimo)
        item.save()
        return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def excluir_item_estoque(request, id):
    """API POST: exclui um item de estoque da empresa da sessão."""
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    item.delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def movimentar_estoque(request, id):
    """API POST: registra uma movimentação (entrada/saída/ajuste) em um item de estoque."""
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    tipo = request.POST.get('tipo')
    quantidade = float(request.POST.get('quantidade', 0))
    observacao = request.POST.get('observacao', '')
    mov = MovimentacaoEstoque.objects.create(
        item=item,
        tipo=tipo,
        quantidade=quantidade,
        data=dt_date.today(),
        observacao=observacao,
        criado_por=request.user,
    )
    if tipo == 'entrada':
        item.quantidade = float(item.quantidade) + quantidade
    elif tipo == 'saida':
        item.quantidade = float(item.quantidade) - quantidade
        # Dar baixa nas matérias-primas vinculadas (ficha técnica)
        if item.produto:
            ficha = ProdutoMateriaPrima.objects.filter(produto_final=item.produto, empresa=empresa)
            for mp in ficha:
                item_mp = ItemEstoque.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
                if item_mp:
                    consumo = float(mp.quantidade) * quantidade
                    item_mp.quantidade = float(item_mp.quantidade) - consumo
                    item_mp.save()
                    MovimentacaoEstoque.objects.create(
                        item=item_mp,
                        tipo='saida',
                        quantidade=consumo,
                        data=dt_date.today(),
                        observacao=f'Consumo automático para {item.produto.nome}',
                        criado_por=request.user,
                    )
    elif tipo == 'ajuste':
        item.quantidade = quantidade
    item.save()
    return JsonResponse({'status': 'ok', 'quantidade_atual': str(item.quantidade)})

# --- AUTOCOMPLETE PRODUTO PARA ESTOQUE ---
@login_required
@require_GET
def autocomplete_produto(request):
    """API GET: busca produtos por nome/categoria para autocomplete no wizard de estoque."""
    empresa = get_empresa_da_sessao(request)
    termo = request.GET.get('q', '')
    categoria = request.GET.get('categoria', '')
    produtos = Produto.objects.filter(empresa=empresa, nome__icontains=termo)
    if categoria:
        produtos = produtos.filter(categoria=categoria)
    produtos = produtos[:10]
    results = []
    for p in produtos:
        item = ItemEstoque.objects.filter(empresa=empresa, produto=p).first()
        estoque_atual = float(item.quantidade) if item else 0
        results.append({
            'id': p.id,
            'nome': p.nome,
            'categoria': p.get_categoria_display(),
            'peso': float(p.peso),
            'unidade': p.unidade,
            'preco_unitario': float(p.preco_unitario),
            'estoque_atual': estoque_atual,
        })
    return JsonResponse({'results': results})

# --- DETALHES DO PRODUTO PARA ESTOQUE (inclui estoque atual) ---
@login_required
@require_GET
def detalhes_produto_estoque(request):
    """API GET: retorna detalhes e estoque atual de um produto pelo id."""
    empresa = get_empresa_da_sessao(request)
    produto_id = request.GET.get('id')
    try:
        p = Produto.objects.get(id=produto_id, empresa=empresa)
        item = ItemEstoque.objects.filter(empresa=empresa, produto=p).first()
        estoque_atual = float(item.quantidade) if item else 0
        return JsonResponse({
            'id': p.id,
            'nome': p.nome,
            'categoria': p.get_categoria_display(),
            'peso': float(p.peso),
            'unidade': p.unidade,
            'preco_unitario': float(p.preco_unitario),
            'estoque_atual': estoque_atual,
        })
    except Produto.DoesNotExist:
        return JsonResponse({'erro': 'Produto não encontrado'}, status=404)

# Endpoint para processar movimentação wizard
@login_required
@require_POST
def movimentar_wizard(request):
    """API POST: processa movimentação em lote (entrada/saída) com baixa automática de matérias-primas."""
    empresa = get_empresa_da_sessao(request)
    tipo = request.POST.get('wizard_tipo', 'entrada')

    # Coletar índices das linhas de produto (prod_produto_id_0, prod_produto_id_1, ...)
    indices_prod = set()
    for key in request.POST:
        if key.startswith('prod_produto_id_'):
            try:
                indices_prod.add(int(key.split('prod_produto_id_')[1]))
            except ValueError:
                pass

    num_prod = len(indices_prod)
    for idx in sorted(indices_prod):
        produto_id = request.POST.get(f'prod_produto_id_{idx}', '').strip()
        qtd = request.POST.get(f'prod_quantidade_{idx}', '0').strip()
        if not produto_id:
            continue
        try:
            qtd = float(qtd)
        except ValueError:
            continue
        if qtd <= 0:
            continue
        try:
            p = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            continue
        item, _ = ItemEstoque.objects.get_or_create(
            empresa=empresa, produto=p,
            defaults={'nome': p.nome, 'quantidade': 0, 'unidade': p.unidade}
        )
        quantidade_mov = quantidade_entrada_base_estoque(p, qtd) if tipo == 'entrada' else qtd
        if tipo == 'entrada':
            item.quantidade = float(item.quantidade) + quantidade_mov
        elif tipo == 'saida':
            item.quantidade = float(item.quantidade) - qtd
        item.save()
        # Observação: "Movimentação em lote" se mais de 1 produto, senão "Movimentação individual"
        if num_prod > 1:
            obs = 'Movimentação em lote'
        else:
            obs = 'Movimentação individual'
        MovimentacaoEstoque.objects.create(
            item=item, tipo=tipo, quantidade=quantidade_mov,
            data=dt_date.today(), observacao=obs,
            criado_por=request.user,
        )
        # Se saída, baixar matérias-primas automaticamente (via ficha técnica)
        if tipo == 'saida':
            ficha = ProdutoMateriaPrima.objects.filter(produto_final=p, empresa=empresa)
            for mp in ficha:
                item_mp = ItemEstoque.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
                if item_mp:
                    item_mp.quantidade = float(item_mp.quantidade) - (float(mp.quantidade) * qtd)
                    item_mp.save()
                    MovimentacaoEstoque.objects.create(
                        item=item_mp, tipo='saida',
                        quantidade=(float(mp.quantidade) * qtd),
                        data=dt_date.today(),
                        observacao=f'Consumo para produção de {p.nome}',
                        criado_por=request.user,
                    )

    # Coletar índices das linhas de perda (perda_produto_id_0, ...)
    indices_perda = set()
    for key in request.POST:
        if key.startswith('perda_produto_id_'):
            try:
                indices_perda.add(int(key.split('perda_produto_id_')[1]))
            except ValueError:
                pass

    for idx in sorted(indices_perda):
        produto_id = request.POST.get(f'perda_produto_id_{idx}', '').strip()
        qtd_perda = request.POST.get(f'perda_quantidade_{idx}', '0').strip()
        if not produto_id:
            continue
        try:
            qtd_perda = float(qtd_perda)
        except ValueError:
            continue
        if qtd_perda <= 0:
            continue
        try:
            p = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            continue
        item = ItemEstoque.objects.filter(empresa=empresa, produto=p).first()
        if item:
            item.quantidade = float(item.quantidade) - qtd_perda
            item.save()
            MovimentacaoEstoque.objects.create(
                item=item, tipo='saida', quantidade=qtd_perda,
                data=dt_date.today(), observacao='Perda registrada',
                criado_por=request.user,
            )

    return JsonResponse({'status': 'ok'})
# Endpoint para listar produtos por categoria (usado no wizard)
@login_required
def listar_produtos_categoria(request):
    """API GET: lista produtos de uma categoria para uso no wizard de movimentação."""
    categoria = request.GET.get('categoria')
    empresa = get_empresa_da_sessao(request)
    produtos = Produto.objects.filter(empresa=empresa, categoria=categoria)
    itens = ItemEstoque.objects.filter(empresa=empresa, produto__in=produtos)
    lista = []
    for p in produtos:
        item = next((i for i in itens if i.produto_id==p.id), None)
        lista.append({
            'id': p.id,
            'nome': p.nome,
            'codigo': p.codigo,
            'estoque': str(item.quantidade) if item else '0',
            'unidade': p.unidade,
            'subcategoria': p.subcategoria or '',
            'preco_unitario': float(p.preco_unitario),
        })
    return JsonResponse({'produtos': lista})

@login_required
def listar_produtos_subcategoria(request):
    """API GET: lista produtos de uma subcategoria para uso no wizard de movimentação."""
    subcategoria_id = request.GET.get('subcategoria_id')
    empresa = get_empresa_da_sessao(request)
    try:
        subcat = SubcategoriaProduto.objects.get(id=subcategoria_id, empresa=empresa)
    except (SubcategoriaProduto.DoesNotExist, TypeError, ValueError):
        return JsonResponse({'produtos': []})
    produtos = Produto.objects.filter(empresa=empresa, subcategoria=subcat)
    itens_dict = {i.produto_id: i for i in ItemEstoque.objects.filter(empresa=empresa, produto__in=produtos)}
    lista = []
    for p in produtos:
        item = itens_dict.get(p.id)
        lista.append({
            'id': p.id,
            'nome': p.nome,
            'codigo': p.codigo,
            'estoque': str(item.quantidade) if item else '0',
            'unidade': p.unidade,
            'preco_unitario': float(p.preco_unitario),
        })
    return JsonResponse({'produtos': lista})

@login_required
@require_POST
def desfazer_movimentacao(request):
    """API POST: reverte uma movimentação de estoque e restaura a quantidade anterior."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=403)

    mov_id = request.POST.get('id')
    try:
        mov = MovimentacaoEstoque.objects.get(id=mov_id, item__empresa=empresa)
        item = mov.item
        # Reverte o estoque
        if mov.tipo == 'entrada':
            item.quantidade = float(item.quantidade) - float(mov.quantidade)
        elif mov.tipo == 'saida':
            item.quantidade = float(item.quantidade) + float(mov.quantidade)
        item.save()
        mov.delete()
        return JsonResponse({'status': 'ok'})
    except MovimentacaoEstoque.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Movimentação não encontrada.'})
# --- REGISTRAR PERDA DE ESTOQUE ---
@login_required
@require_POST
def registrar_perda(request):
    """API POST: registra uma perda de produto no estoque."""
    empresa = get_empresa_da_sessao(request)
    produto_id = request.POST.get('produto_id')
    quantidade = float(request.POST.get('quantidade', 0))
    try:
        produto = Produto.objects.get(id=produto_id, empresa=empresa)
        item = ItemEstoque.objects.filter(produto=produto, empresa=empresa).first()
        if not item:
            return JsonResponse({'status': 'erro', 'mensagem': 'Item de estoque não encontrado para o produto.'})
        if quantidade <= 0:
            return JsonResponse({'status': 'erro', 'mensagem': 'Quantidade inválida.'})
        # Atualiza estoque
        item.quantidade = float(item.quantidade) - quantidade
        item.save()
        # Registra movimentação
        MovimentacaoEstoque.objects.create(
            item=item,
            tipo='saida',
            quantidade=quantidade,
            data=dt_date.today(),
            observacao='perda',
            criado_por=request.user,
        )
        return JsonResponse({'status': 'ok'})
    except Produto.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Produto não encontrado.'})

# -----------------------------
# API: Subcategorias e Produtos de Matéria-Prima
# -----------------------------

@login_required
@require_GET
def listar_materias_primas_por_subcategoria(request):
    """API GET: lista matérias-primas agrupadas por subcategoria para uso em ficha técnica."""
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'}, status=400)

    # Busca subcategorias de matéria-prima
    subcategorias = SubcategoriaProduto.objects.filter(empresa=empresa, categoria__nome__icontains='matéria')
    resultado = []
    for sub in subcategorias:
        produtos = Produto.objects.filter(empresa=empresa, categoria='materia_prima', subcategoria=sub.nome)
        resultado.append({
            'subcategoria_id': sub.id,
            'subcategoria_nome': sub.nome,
            'produtos': [
                {'id': p.id, 'nome': p.nome, 'unidade': p.unidade, 'descricao': p.descricao or ''}
                for p in produtos
            ]
        })

    return JsonResponse({'status': 'ok', 'subcategorias': resultado})


@login_required
def movimentacoes_por_item(request, id):
    """API GET: retorna o histórico de movimentações de um item de estoque."""
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    movs = MovimentacaoEstoque.objects.filter(item=item).order_by('-data', '-id')
    data = []
    for m in movs:
        data.append({
            'id': m.id,
            'tipo': m.tipo,
            'quantidade': str(m.quantidade),
            'data': str(m.data),
            'usuario': m.criado_por.username if m.criado_por else '-',
            'observacao': m.observacao or '',
        })
    return JsonResponse({'movimentacoes': data})


@login_required
def editar_movimentacao_estoque(request, id):
    """API GET/POST: retorna ou edita uma movimentação de estoque existente."""
    empresa = get_empresa_da_sessao(request)
    mov = get_object_or_404(MovimentacaoEstoque, id=id, item__empresa=empresa)

    if request.method == 'GET':
        return JsonResponse({
            'id': mov.id,
            'tipo': mov.tipo,
            'quantidade': str(mov.quantidade),
            'data': str(mov.data),
            'observacao': mov.observacao,
            'produto_id': mov.item.produto.id if mov.item.produto else None,
            'produto_nome': mov.item.nome,
            'estoque_atual': str(mov.item.quantidade),
            'subcategoria_id': mov.item.produto.subcategoria.id if mov.item.produto and mov.item.produto.subcategoria else None,
        })

    elif request.method == 'POST':
        tipo = request.POST.get('editar_wizard_tipo', mov.tipo)

        # Row 0 — atualiza a movimentação original
        qtd_0_raw = request.POST.get('prod_quantidade_0')
        if qtd_0_raw:
            try:
                qtd_0 = float(qtd_0_raw)
                item = mov.item
                # Reverte o efeito anterior no estoque
                if mov.tipo == 'entrada':
                    item.quantidade = float(item.quantidade) - float(mov.quantidade)
                elif mov.tipo == 'saida':
                    item.quantidade = float(item.quantidade) + float(mov.quantidade)
                # Aplica o novo efeito
                if tipo == 'entrada':
                    item.quantidade = float(item.quantidade) + qtd_0
                elif tipo == 'saida':
                    item.quantidade = float(item.quantidade) - qtd_0
                item.save()
                mov.tipo = tipo
                mov.quantidade = qtd_0
                mov.save()
            except (ValueError, TypeError):
                pass

        # Rows 1+ — cria novas movimentações para itens adicionais
        indices = set()
        for key in request.POST:
            if key.startswith('prod_produto_id_'):
                try:
                    idx = int(key.split('prod_produto_id_')[1])
                    if idx > 0:
                        indices.add(idx)
                except ValueError:
                    pass

        for idx in sorted(indices):
            produto_id = request.POST.get(f'prod_produto_id_{idx}', '').strip()
            qtd_str = request.POST.get(f'prod_quantidade_{idx}', '0').strip()
            if not produto_id:
                continue
            try:
                qtd = float(qtd_str)
            except ValueError:
                continue
            if qtd <= 0:
                continue
            try:
                p = Produto.objects.get(id=produto_id, empresa=empresa)
            except Produto.DoesNotExist:
                continue
            item_new, _ = ItemEstoque.objects.get_or_create(
                empresa=empresa, produto=p,
                defaults={'nome': p.nome, 'quantidade': 0, 'unidade': p.unidade}
            )
            if tipo == 'entrada':
                item_new.quantidade = float(item_new.quantidade) + qtd
            elif tipo == 'saida':
                item_new.quantidade = float(item_new.quantidade) - qtd
            item_new.save()
            MovimentacaoEstoque.objects.create(
                item=item_new, tipo=tipo, quantidade=qtd,
                data=dt_date.today(), observacao='Adicionado via edição',
                criado_por=request.user,
            )

        return JsonResponse({'status': 'ok'})

    return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)


# =============================================
# COMERCIAL
# =============================================

@login_required
def comercial(request):
    """Página comercial: exibe orçamentos, entradas comerciais, fornecedores e categorias."""
    empresa = get_empresa_da_sessao(request)
    orcamentos = Orcamento.objects.filter(empresa=empresa).order_by('-id')
    entradas = EntradaComercial.objects.filter(empresa=empresa).prefetch_related('itens').select_related('fornecedor', 'criado_por')
    fornecedores = Fornecedor.objects.filter(empresa=empresa)
    categorias = CategoriaProduto.objects.filter(empresa=empresa).prefetch_related('subcategorias')
    return render(request, 'comercial.html', {
        'orcamentos': orcamentos,
        'entradas': entradas,
        'fornecedores': fornecedores,
        'categorias': categorias,
    })


@login_required
def criar_entrada_comercial(request):
    """API POST: registra uma entrada comercial (compra) e atualiza o estoque dos produtos."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    data_str = request.POST.get('data', '')
    fornecedor_id = request.POST.get('fornecedor_id', '').strip()
    observacao = request.POST.get('observacao', '').strip()
    itens_json = request.POST.get('itens', '[]')
    try:
        itens = json.loads(itens_json)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'erro', 'mensagem': 'Itens inválidos.'})
    if not data_str or not itens:
        return JsonResponse({'status': 'erro', 'mensagem': 'Data e itens são obrigatórios.'})
    try:
        data = dt_date.fromisoformat(data_str)
    except ValueError:
        return JsonResponse({'status': 'erro', 'mensagem': 'Data inválida.'})
    fornecedor = None
    if fornecedor_id:
        try:
            fornecedor = Fornecedor.objects.get(id=fornecedor_id, empresa=empresa)
        except Fornecedor.DoesNotExist:
            pass
    entrada = EntradaComercial.objects.create(
        empresa=empresa,
        fornecedor=fornecedor,
        data=data,
        observacao=observacao,
        criado_por=request.user,
    )
    for item_data in itens:
        produto_id = item_data.get('produto_id', '').strip()
        qtd_str = str(item_data.get('quantidade', '0'))
        preco_str = str(item_data.get('preco_unitario', '0'))
        if not produto_id:
            continue
        try:
            qtd = float(qtd_str)
            preco = float(preco_str)
        except (ValueError, TypeError):
            continue
        if qtd <= 0:
            continue
        try:
            produto = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            continue
        ItemEntradaComercial.objects.create(
            entrada=entrada, produto=produto, quantidade=qtd, preco_unitario=preco
        )
        # Atualiza estoque
        item_estoque, _ = ItemEstoque.objects.get_or_create(
            empresa=empresa, produto=produto,
            defaults={'nome': produto.nome, 'quantidade': 0, 'unidade': produto.unidade}
        )
        quantidade_mov = quantidade_entrada_base_estoque(produto, qtd)
        item_estoque.quantidade = float(item_estoque.quantidade) + quantidade_mov
        if preco > 0:
            item_estoque.preco_custo = preco
        item_estoque.save()
        MovimentacaoEstoque.objects.create(
            item=item_estoque,
            tipo='entrada',
            quantidade=quantidade_mov,
            data=data,
            observacao=f'Entrada Comercial #{entrada.id}' + (f' - {fornecedor.nome}' if fornecedor else ''),
            criado_por=request.user,
        )
    return JsonResponse({'status': 'ok'})


@login_required
def detalhe_entrada_comercial(request, id):
    """API GET: retorna os dados detalhados de uma entrada comercial."""
    empresa = get_empresa_da_sessao(request)
    entrada = get_object_or_404(EntradaComercial, id=id, empresa=empresa)
    itens = entrada.itens.select_related('produto').all()

    itens_data = []
    for i in itens:
        try:
            est = ItemEstoque.objects.get(empresa=empresa, produto=i.produto)
            estoque_atual = float(est.quantidade)
        except ItemEstoque.DoesNotExist:
            estoque_atual = None
        itens_data.append({
            'produto': i.produto.nome,
            'produto_id': i.produto.id,
            'quantidade': str(i.quantidade),
            'preco_unitario': str(i.preco_unitario),
            'estoque_atual': estoque_atual,
        })

    return JsonResponse({
        'entrada': {
            'id': entrada.id,
            'data': entrada.data.strftime('%d/%m/%Y'),
            'data_iso': entrada.data.isoformat(),
            'fornecedor': entrada.fornecedor.nome if entrada.fornecedor else None,
            'fornecedor_id': entrada.fornecedor.id if entrada.fornecedor else None,
            'observacao': entrada.observacao,
            'itens': itens_data,
        }
    })


@login_required
def excluir_entrada_comercial(request, id):
    """API POST: exclui uma entrada comercial e reverte o estoque dos itens relacionados."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    entrada = get_object_or_404(EntradaComercial, id=id, empresa=empresa)
    # Reverter estoque
    for item_data in entrada.itens.select_related('produto').all():
        try:
            item_estoque = ItemEstoque.objects.get(empresa=empresa, produto=item_data.produto)
            item_estoque.quantidade = float(item_estoque.quantidade) - float(item_data.quantidade)
            item_estoque.save()
            # Remover movimentação correspondente
            MovimentacaoEstoque.objects.filter(
                item=item_estoque,
                tipo='entrada',
                observacao__startswith=f'Entrada Comercial #{entrada.id}',
            ).delete()
        except ItemEstoque.DoesNotExist:
            pass
    entrada.delete()
    return JsonResponse({'status': 'ok'})


@login_required
def editar_entrada_comercial(request, id):
    """API POST: edita uma entrada comercial revertendo e recriando itens e movimentações de estoque."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    entrada = get_object_or_404(EntradaComercial, id=id, empresa=empresa)

    data_str = request.POST.get('data', '').strip()
    fornecedor_id = request.POST.get('fornecedor_id', '').strip()
    observacao = request.POST.get('observacao', '').strip()
    itens_json = request.POST.get('itens', '[]')
    try:
        novos_itens = json.loads(itens_json)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'erro', 'mensagem': 'Itens inválidos.'})

    nova_data = None
    try:
        nova_data = dt_date.fromisoformat(data_str)
    except ValueError:
        return JsonResponse({'status': 'erro', 'mensagem': 'Data inválida.'})

    # 1. Reverter estoque e movimentações dos itens antigos
    for item_data in entrada.itens.select_related('produto').all():
        try:
            item_est = ItemEstoque.objects.get(empresa=empresa, produto=item_data.produto)
            item_est.quantidade = float(item_est.quantidade) - float(item_data.quantidade)
            item_est.save()
            MovimentacaoEstoque.objects.filter(
                item=item_est,
                tipo='entrada',
                observacao__startswith=f'Entrada Comercial #{entrada.id}',
            ).delete()
        except ItemEstoque.DoesNotExist:
            pass

    # 2. Atualizar campos da entrada
    fornecedor = None
    if fornecedor_id:
        try:
            fornecedor = Fornecedor.objects.get(id=fornecedor_id, empresa=empresa)
        except Fornecedor.DoesNotExist:
            pass
    entrada.fornecedor = fornecedor
    entrada.data = nova_data
    entrada.observacao = observacao
    entrada.save()

    # 3. Remover itens antigos e criar novos
    entrada.itens.all().delete()
    for item_data in novos_itens:
        produto_id = str(item_data.get('produto_id', '')).strip()
        try:
            qtd = float(item_data.get('quantidade', 0))
            preco = float(item_data.get('preco_unitario', 0))
        except (ValueError, TypeError):
            continue
        if not produto_id or qtd <= 0:
            continue
        try:
            produto = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            continue
        ItemEntradaComercial.objects.create(
            entrada=entrada, produto=produto, quantidade=qtd, preco_unitario=preco
        )
        item_est, _ = ItemEstoque.objects.get_or_create(
            empresa=empresa, produto=produto,
            defaults={'nome': produto.nome, 'quantidade': 0, 'unidade': produto.unidade}
        )
        item_est.quantidade = float(item_est.quantidade) + qtd
        if preco > 0:
            item_est.preco_custo = preco
        item_est.save()
        MovimentacaoEstoque.objects.create(
            item=item_est, tipo='entrada', quantidade=qtd, data=nova_data,
            observacao=f'Entrada Comercial #{entrada.id}' + (f' - {fornecedor.nome}' if fornecedor else ''),
            criado_por=request.user,
        )
    return JsonResponse({'status': 'ok'})


@login_required
def relatorio_entradas_fornecedor(request):
    """API GET: gera relatório de entradas comerciais agrupado por fornecedor."""
    empresa = get_empresa_da_sessao(request)
    data_ini = request.GET.get('data_ini', '')
    data_fim = request.GET.get('data_fim', '')
    fornecedor_id = request.GET.get('fornecedor_id', '')

    entradas = EntradaComercial.objects.filter(empresa=empresa)
    if data_ini:
        try:
            entradas = entradas.filter(data__gte=dt_date.fromisoformat(data_ini))
        except ValueError:
            pass
    if data_fim:
        try:
            entradas = entradas.filter(data__lte=dt_date.fromisoformat(data_fim))
        except ValueError:
            pass
    if fornecedor_id:
        entradas = entradas.filter(fornecedor_id=fornecedor_id)

    # Agrupado por fornecedor
    resultado = []
    fornecedores_ids = entradas.values_list('fornecedor_id', flat=True).distinct()
    for forn_id in fornecedores_ids:
        ents = entradas.filter(fornecedor_id=forn_id)
        itens = ItemEntradaComercial.objects.filter(entrada__in=ents)
        valor_total = sum(float(i.quantidade) * float(i.preco_unitario) for i in itens)
        qtd_total = sum(float(i.quantidade) for i in itens)
        if forn_id:
            try:
                forn = Fornecedor.objects.get(id=forn_id, empresa=empresa)
                nome_forn = forn.nome
            except Fornecedor.DoesNotExist:
                nome_forn = 'Desconhecido'
        else:
            nome_forn = 'Sem Fornecedor'
        # Detalhes por entrada
        detalhes = []
        for ent in ents.order_by('-data'):
            itens_ent = ItemEntradaComercial.objects.filter(entrada=ent).select_related('produto')
            valor_ent = sum(float(i.quantidade) * float(i.preco_unitario) for i in itens_ent)
            detalhes.append({
                'id': ent.id,
                'data': ent.data.strftime('%d/%m/%Y'),
                'observacao': ent.observacao or '',
                'num_itens': itens_ent.count(),
                'valor': round(valor_ent, 2),
                'itens': [
                    {
                        'produto': i.produto.nome,
                        'quantidade': float(i.quantidade),
                        'preco_unitario': float(i.preco_unitario),
                        'total': round(float(i.quantidade) * float(i.preco_unitario), 2),
                    }
                    for i in itens_ent
                ],
            })
        resultado.append({
            'fornecedor_id': forn_id,
            'fornecedor': nome_forn,
            'num_entradas': ents.count(),
            'qtd_total': round(qtd_total, 2),
            'valor_total': round(valor_total, 2),
            'detalhes': detalhes,
        })

    resultado.sort(key=lambda x: x['valor_total'], reverse=True)
    return JsonResponse({'status': 'ok', 'resultado': resultado})


# =============================================
# FORNECEDOR (AJAX)
# =============================================

@login_required
def criar_fornecedor_ajax(request):
    """API POST: cria um novo fornecedor para a empresa da sessão."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    nome = request.POST.get('nome', '').strip()
    if not nome:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nome é obrigatório.'})
    f = Fornecedor.objects.create(
        empresa=empresa,
        nome=nome,
        cnpj_cpf=request.POST.get('cnpj_cpf', '').strip(),
        telefone=request.POST.get('telefone', '').strip(),
        email=request.POST.get('email', '').strip(),
        endereco=request.POST.get('endereco', '').strip(),
    )
    return JsonResponse({'status': 'ok', 'id': f.id, 'nome': f.nome})


@login_required
def editar_fornecedor_ajax(request, id):
    """API POST: atualiza os dados de um fornecedor da empresa da sessão."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    f = get_object_or_404(Fornecedor, id=id, empresa=empresa)
    nome = request.POST.get('nome', '').strip()
    if not nome:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nome é obrigatório.'})
    f.nome = nome
    f.cnpj_cpf = request.POST.get('cnpj_cpf', '').strip()
    f.telefone = request.POST.get('telefone', '').strip()
    f.email = request.POST.get('email', '').strip()
    f.endereco = request.POST.get('endereco', '').strip()
    f.save()
    return JsonResponse({'status': 'ok'})


@login_required
def excluir_fornecedor_ajax(request, id):
    """API POST: exclui um fornecedor da empresa da sessão."""
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    f = get_object_or_404(Fornecedor, id=id, empresa=empresa)
    f.delete()
    return JsonResponse({'status': 'ok'})


def _aplicar_classes_senha(form):
    """Utilitário: aplica classes CSS Bootstrap aos campos do formulário de troca de senha."""
    attrs = {'class': 'form-control', 'autocomplete': 'off'}
    form.fields['old_password'].widget.attrs.update(attrs)
    form.fields['new_password1'].widget.attrs.update(attrs)
    form.fields['new_password2'].widget.attrs.update(attrs)
    return form

@login_required
def perfil(request):
    """Página de perfil do usuário com opção de alterar senha."""
    user = request.user
    form_senha = _aplicar_classes_senha(PasswordChangeForm(user))
    senha_alterada = False

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'trocar_senha':
            form_senha = _aplicar_classes_senha(PasswordChangeForm(user, request.POST))
            if form_senha.is_valid():
                form_senha.save()
                update_session_auth_hash(request, form_senha.user)
                senha_alterada = True
                form_senha = _aplicar_classes_senha(PasswordChangeForm(user))

    return render(request, 'perfil.html', {
        'form_senha': form_senha,
        'senha_alterada': senha_alterada,
    })


@login_required
def documentacao(request):
    """Exibe a página de documentação do sistema."""
    return render(request, 'documentacao.html')

