from django.shortcuts import render, get_object_or_404, redirect
from .models import UserEmpresa
from django.contrib.auth import logout
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.db.models import Q
from django.db.models import Sum, F, FloatField
from django.utils import timezone
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import logout
from .models import (
    Cliente, Produto, Servico, Orcamento, Banco, LancamentoBancario,
    ItemEstoque, MovimentacaoEstoque, Fornecedor, EntradaComercial, ItemEntradaComercial
)
from .forms import (
    ItemOrcamentoForm, BancoForm, LancamentoBancarioForm,
    MovimentacaoEstoqueForm
)
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q
from django.db.models import Sum, F, FloatField
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from .models import ItemOrcamento


# -----------------------------
# INDEX
# -----------------------------
def index(request):
    return render(request, 'index.html')

# -----------------------------
# LOGIN / LOGOUT
# -----------------------------
def login_view(request):
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
    logout(request)
    return redirect('core:index')


# -----------------------------
# SELECIONAR EMPRESA
# -----------------------------
@login_required
def selecionar_empresa(request):
    # Busca as empresas vinculadas ao usuário logado
    empresas_vinculadas = UserEmpresa.objects.filter(user=request.user)

    if request.method == 'POST':
        empresa_id = request.POST.get('empresa_id')
        if empresa_id:
            request.session['empresa_id'] = int(empresa_id)
            return redirect('core:dashboard')

    return render(request, 'selecionar_empresa.html', {
        'empresas': empresas_vinculadas  # 👈 nome da variável usada no template
    })


# -----------------------------
# FUNÇÃO AUXILIAR
# -----------------------------

# Busca empresa pela sessão
def get_empresa_da_sessao(request):
    from .models import Empresa
    empresa_id = request.session.get('empresa_id')
    if not empresa_id:
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
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return render(request, "erro.html", {"mensagem": "Nenhuma empresa associada."})

    from .models import ItemEstoque, EntradaComercial, ItemEntradaComercial, Banco, LancamentoBancario

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
    from .models import MovimentacaoEstoque
    from django.db.models import Sum as _Sum
    top_saidas = (
        MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='saida')
        .values('item__id', 'item__nome', 'item__unidade')
        .annotate(total=_Sum('quantidade'))
        .order_by('-total')[:6]
    )
    top_entradas = (
        MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='entrada')
        .values('item__id', 'item__nome', 'item__unidade')
        .annotate(total=_Sum('quantidade'))
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
from .forms import BancoForm, LancamentoBancarioForm
from .models import Banco, LancamentoBancario
import pandas as pd
from django.http import HttpResponse

@login_required
def fluxo_bancario_dashboard(request):
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
    if request.method != 'POST':
        return HttpResponse('Método não permitido', status=405)
    empresa = get_empresa_da_sessao(request)
    lancamento = get_object_or_404(LancamentoBancario, id=id, banco__empresa=empresa)
    banco_id = lancamento.banco.id
    lancamento.delete()
    return redirect(f"/fluxo-bancario/?banco={banco_id}")


@login_required
def importar_lancamentos_excel(request):
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
    import io
    import pandas as pd
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
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'mensagem': 'Empresa não encontrada.'})

    # Função utilitária para tratar decimais do formato brasileiro
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


    preco = parse_decimal_br(request.POST.get('preco'))
    preco_unitario = parse_decimal_br(request.POST.get('preco_unitario'))
    estoque_inicial = parse_decimal_br(request.POST.get('estoque_inicial'))
    peso = parse_decimal_br(request.POST.get('peso'))

    subcat_id = request.POST.get('subcategoria')
    from .models import SubcategoriaProduto
    subcategoria = None
    if subcat_id:
        try:
            subcategoria = SubcategoriaProduto.objects.get(id=subcat_id, empresa=empresa)
        except SubcategoriaProduto.DoesNotExist:
            subcategoria = None
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
    from .models import ItemEstoque, MovimentacaoEstoque
    item_estoque = ItemEstoque.objects.create(
        empresa=empresa,
        produto=produto,
        nome=produto.nome,
        codigo=produto.codigo,
        quantidade=estoque_inicial,
        unidade=produto.unidade,
    )
    # Se estoque inicial > 0, registra movimentação de entrada
    if estoque_inicial > 0:
        from datetime import date as dt_date
        MovimentacaoEstoque.objects.create(
            item=item_estoque,
            tipo='entrada',
            quantidade=estoque_inicial,
            data=dt_date.today(),
            observacao='Estoque inicial',
            criado_por=request.user,
        )

    # Salvar ficha técnica de matéria-prima
    from .models import ProdutoMateriaPrima
    ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa).delete()
    mp_keys = [k for k in request.POST if k.startswith('mp_produto_id_')]
    for key in mp_keys:
        idx = key.replace('mp_produto_id_', '')
        mp_id = request.POST.get(key, '').strip()
        mp_qtd = request.POST.get(f'mp_quantidade_{idx}', '0').strip()
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
            defaults={'quantidade': mp_qtd},
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
    empresa = get_empresa_da_sessao(request)
    if request.method == 'POST':
        try:
            produto = Produto.objects.get(id=id, empresa=empresa)
            # Excluir ItemEstoque vinculado antes de excluir o produto
            from .models import ItemEstoque
            ItemEstoque.objects.filter(produto=produto, empresa=empresa).delete()
            produto.delete()
            return JsonResponse({'status': 'ok', 'mensagem': 'Produto excluído com sucesso'})
        except Produto.DoesNotExist:
            return JsonResponse({'status': 'erro', 'mensagem': 'Produto não encontrado'})
    return JsonResponse({'status': 'erro', 'mensagem': 'Método inválido'})
@login_required
def editar_produto(request, id):
    empresa = get_empresa_da_sessao(request)
    try:
        produto = Produto.objects.get(id=id, empresa=empresa)
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
            from .models import ProdutoMateriaPrima
            ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa).delete()
            mp_keys = [k for k in request.POST if k.startswith('mp_produto_id_')]
            for key in mp_keys:
                idx = key.replace('mp_produto_id_', '')
                mp_id = request.POST.get(key, '').strip()
                mp_qtd = request.POST.get(f'mp_quantidade_{idx}', '0').strip()
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
                    defaults={'quantidade': mp_qtd},
                )

            return JsonResponse({'status': 'ok', 'id': produto.id})
        # Buscar estoque inicial (quantidade do ItemEstoque vinculado)
        from .models import ItemEstoque, ProdutoMateriaPrima
        item_estoque = ItemEstoque.objects.filter(produto=produto, empresa=empresa).first()
        estoque_inicial = item_estoque.quantidade if item_estoque else 0
        def format_real(valor):
            return ("%.2f" % float(valor)).replace('.', ',')
        # Buscar ficha técnica de matéria-prima
        materias_primas = []
        for mp in ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa):
            materias_primas.append({
                'id': mp.materia_prima.id,
                'nome': mp.materia_prima.nome,
                'quantidade': float(mp.quantidade),
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
    empresa_id = request.session.get('empresa_id')
    if not empresa_id:
        return redirect('core:selecionar_empresa')

    orcamentos = Orcamento.objects.filter(empresa_id=empresa_id).order_by('-criado_em')
    clientes = Cliente.objects.filter(empresa_id=empresa_id)

    return render(request, 'orcamentos.html', {
        'orcamentos': orcamentos,
        'clientes': clientes,
    })


@login_required
@require_POST
def criar_orcamento(request):
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
                from datetime import date as _dt
                item_est, _ = ItemEstoque.objects.get_or_create(
                    empresa=empresa, produto=ref,
                    defaults={'nome': ref.nome, 'quantidade': 0, 'unidade': ref.unidade}
                )
                item_est.quantidade = float(item_est.quantidade) - qtd
                item_est.save()
                MovimentacaoEstoque.objects.create(
                    item=item_est, tipo='saida', quantidade=qtd,
                    data=_dt.today(),
                    observacao=f'Venda - Orca #{orcamento.numero}',
                    criado_por=request.user,
                )

        orcamento.save()
        return JsonResponse({'status': 'ok'})

    except Exception as e:
        return JsonResponse({'status': 'erro', 'mensagem': str(e)})


@login_required
@require_POST
def editar_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(
        Orcamento,
        id=orcamento_id,
        empresa_id=request.session.get('empresa_id')
    )

    try:
        data = request.POST
        itens = json.loads(data.get('itens', '[]'))
        desconto = float(data.get('desconto', 0) or 0)

        empresa = get_empresa_da_sessao(request)

        # Reverter baixas de estoque dos itens antigos
        for item_antigo in ItemOrcamento.objects.filter(orcamento=orcamento).select_related('produto'):
            if item_antigo.produto:
                try:
                    item_est = ItemEstoque.objects.get(empresa=empresa, produto=item_antigo.produto)
                    item_est.quantidade = float(item_est.quantidade) + float(item_antigo.quantidade)
                    item_est.save()
                except ItemEstoque.DoesNotExist:
                    pass

        orcamento.cliente_id = data.get('cliente')
        orcamento.solicitante = data.get('solicitante')
        orcamento.previsao_entrega = data.get('previsao_entrega') or None
        orcamento.forma_pagamento = data.get('forma_pagamento')
        orcamento.vencimento = data.get('vencimento') or None
        orcamento.observacao = data.get('observacao')
        orcamento.responsavel = data.get('responsavel')
        orcamento.desconto = desconto

        # Limpa itens antigos
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
            # Nova baixa no estoque (editar_orcamento)
            if tipo == 'produto' and ref:
                from datetime import date as _dt2
                item_est2, _ = ItemEstoque.objects.get_or_create(
                    empresa=empresa, produto=ref,
                    defaults={'nome': ref.nome, 'quantidade': 0, 'unidade': ref.unidade}
                )
                item_est2.quantidade = float(item_est2.quantidade) - qtd
                item_est2.save()
                MovimentacaoEstoque.objects.create(
                    item=item_est2, tipo='saida', quantidade=qtd,
                    data=_dt2.today(),
                    observacao=f'Venda - Orca #{orcamento.numero}',
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

    orc = get_object_or_404(Orcamento, id=orcamento_id)
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
    orcamento = get_object_or_404(
        Orcamento,
        id=orcamento_id,
        empresa_id=request.session.get('empresa_id')  # ajuste se o nome da session for diferente
    )
    try:
        orcamento.delete()
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "erro", "mensagem": str(e)})


@login_required
def imprimir_orcamento(request, orcamento_id):
    empresa_id = request.session.get('empresa_id')
    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa_id=empresa_id)
    itens = ItemOrcamento.objects.filter(orcamento=orcamento)

    return render(request, 'imprimir.html', {
        'orcamento': orcamento,
        'itens': itens,
    })

@login_required
def orcamento_detalhe_json(request, orcamento_id):
    """Retorna os dados do orçamento em JSON para o modal de edição."""
    empresa_id = request.session.get('empresa_id')
    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa_id=empresa_id)
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

    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa_id=request.session.get('empresa_id'))
    try:
        data = request.POST
        itens = json.loads(data.get('itens', '[]'))
        desconto = float(data.get('desconto', 0) or 0)

        orcamento.cliente_id = data.get('cliente')
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

            model = Produto if tipo == 'produto' else Servico
            ref = model.objects.filter(id=item.get('id_item')).first()

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
    orcamento = get_object_or_404(Orcamento, id=orcamento_id, empresa_id=request.session.get('empresa_id'))
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
    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa_id=request.session.get('empresa_id'))
    form = ItemOrcamentoForm(request.POST, instance=item)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'erro', 'erros': form.errors})


@login_required
@require_POST
def excluir_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa_id=request.session.get('empresa_id'))
    item.delete()
    return JsonResponse({'status': 'ok'})


@login_required
def detalhe_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id, orcamento__empresa_id=request.session.get('empresa_id'))
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

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
@login_required
def utf8_json_response(data):
    return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False})


@login_required
def autocomplete_cliente(request):
    empresa_id = request.session.get('empresa_id')
    term = request.GET.get('term', '')
    cliente_id = request.GET.get('id')

    clientes = Cliente.objects.filter(empresa_id=empresa_id)

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
    termo = request.GET.get('term', '')
    produtos = Produto.objects.filter(nome__icontains=termo)
    servicos = Servico.objects.filter(nome__icontains=termo)

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
    empresa = get_empresa_da_sessao(request)
    if not empresa:
        return redirect('core:index')

    from .models import ItemEstoque, CategoriaProduto, SubcategoriaProduto
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

    from django.db.models import Prefetch, OuterRef, Subquery, DecimalField
    from .models import ItemEstoque as _IE

    # Anotação de estoque atual em cada produto
    estoque_subquery = Subquery(
        _IE.objects.filter(produto=OuterRef('pk'), empresa=empresa).values('quantidade')[:1],
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
    empresa = get_empresa_da_sessao(request)
    modulos = ['Financeiro', 'Dashboard', 'Orçamentos', 'Configurações', 'Relatórios', 'Outro']
    
    context = {
    'usuario': request.user,
    'modulos': modulos,
    'empresa': empresa,
}
    return render(request, 'suporte.html', context)

from django.views.decorators.csrf import csrf_exempt
# -----------------------------
# BANCOS (AJAX)
# -----------------------------
@login_required
@require_POST
def criar_banco_ajax(request):
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
    empresa = get_empresa_da_sessao(request)
    itens = ItemEstoque.objects.filter(empresa=empresa, produto__isnull=False)
    movimentacoes = MovimentacaoEstoque.objects.filter(item__empresa=empresa).order_by('-data', '-id')[:100]
    perdas = MovimentacaoEstoque.objects.filter(item__empresa=empresa, tipo='saida', observacao__icontains='perda').order_by('-data', '-id')[:50]
    # Valor total do estoque
    valor_total_estoque = 0
    for item in itens:
        if item.produto and item.produto.preco_unitario:
            valor_total_estoque += float(item.quantidade) * float(item.produto.preco_unitario)
    from .models import CategoriaProduto
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


@login_required
@require_POST
def criar_item_estoque(request):
    empresa = get_empresa_da_sessao(request)
    produto_id = request.POST.get('produto_id')
    produto = None
    if produto_id:
        from .models import Produto
        try:
            produto = Produto.objects.get(id=produto_id, empresa=empresa)
        except Produto.DoesNotExist:
            produto = None
    from .models import ItemEstoque
    quantidade_nova = float(request.POST.get('quantidade', 0))
    tipo_mov = request.POST.get('tipo', 'entrada')  # 'entrada' ou 'saida'
    if produto:
        item = ItemEstoque.objects.filter(empresa=empresa, produto=produto).first()
        if item:
            # Já existe, soma ou subtrai do estoque atual
            if tipo_mov == 'entrada':
                item.quantidade = float(item.quantidade) + quantidade_nova
            elif tipo_mov == 'saida':
                item.quantidade = float(item.quantidade) - quantidade_nova
                # Dar baixa nas matérias-primas vinculadas (ficha técnica)
                from .models import ProdutoMateriaPrima, ItemEstoque as IE
                ficha = ProdutoMateriaPrima.objects.filter(produto_final=produto, empresa=empresa)
                for mp in ficha:
                    item_mp = IE.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
                    if item_mp:
                        item_mp.quantidade = float(item_mp.quantidade) - (float(mp.quantidade) * quantidade_nova)
                        item_mp.save()
                        # Registrar movimentação de saída da matéria-prima
                        from .models import MovimentacaoEstoque
                        from datetime import date as dt_date
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
            from .models import MovimentacaoEstoque
            from datetime import date as dt_date
            MovimentacaoEstoque.objects.create(
                item=item,
                tipo=tipo_mov,
                quantidade=quantidade_nova,
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
                quantidade=quantidade_nova if tipo_mov == 'entrada' else -quantidade_nova,
                unidade=request.POST.get('unidade', 'un'),
                preco_custo=request.POST.get('preco_custo', 0),
                estoque_minimo=request.POST.get('estoque_minimo', 0),
            )
            # Registrar movimentação
            from .models import MovimentacaoEstoque
            from datetime import date as dt_date
            MovimentacaoEstoque.objects.create(
                item=item,
                tipo=tipo_mov,
                quantidade=quantidade_nova,
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
        from .models import MovimentacaoEstoque
        from datetime import date as dt_date
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
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    item.delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def movimentar_estoque(request, id):
    empresa = get_empresa_da_sessao(request)
    item = get_object_or_404(ItemEstoque, id=id, empresa=empresa)
    tipo = request.POST.get('tipo')
    quantidade = float(request.POST.get('quantidade', 0))
    observacao = request.POST.get('observacao', '')
    from datetime import date as dt_date
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
            from .models import ProdutoMateriaPrima, ItemEstoque as IE
            ficha = ProdutoMateriaPrima.objects.filter(produto_final=item.produto, empresa=empresa)
            for mp in ficha:
                item_mp = IE.objects.filter(produto=mp.materia_prima, empresa=empresa).first()
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

from django.views.decorators.http import require_GET
# --- AUTOCOMPLETE PRODUTO PARA ESTOQUE ---
@login_required
@require_GET
def autocomplete_produto(request):
    empresa = get_empresa_da_sessao(request)
    termo = request.GET.get('q', '')
    categoria = request.GET.get('categoria', '')
    produtos = Produto.objects.filter(empresa=empresa, nome__icontains=termo)
    if categoria:
        produtos = produtos.filter(categoria=categoria)
    produtos = produtos[:10]
    results = []
    for p in produtos:
        from .models import ItemEstoque
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
    empresa = get_empresa_da_sessao(request)
    produto_id = request.GET.get('id')
    from .models import ItemEstoque
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
    empresa = get_empresa_da_sessao(request)
    tipo = request.POST.get('wizard_tipo', 'entrada')
    from .models import Produto, ItemEstoque, MovimentacaoEstoque, ProdutoMateriaPrima
    from datetime import date as dt_date

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
        if tipo == 'entrada':
            item.quantidade = float(item.quantidade) + qtd
        elif tipo == 'saida':
            item.quantidade = float(item.quantidade) - qtd
        item.save()
        # Observação: "Movimentação em lote" se mais de 1 produto, senão "Movimentação individual"
        if num_prod > 1:
            obs = 'Movimentação em lote'
        else:
            obs = 'Movimentação individual'
        MovimentacaoEstoque.objects.create(
            item=item, tipo=tipo, quantidade=qtd,
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
from django.http import JsonResponse
@login_required
def listar_produtos_categoria(request):
    categoria = request.GET.get('categoria')
    empresa = get_empresa_da_sessao(request)
    from .models import Produto, ItemEstoque
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
    subcategoria_id = request.GET.get('subcategoria_id')
    empresa = get_empresa_da_sessao(request)
    from .models import Produto, ItemEstoque, SubcategoriaProduto
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
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

@login_required
@require_POST
def desfazer_movimentacao(request):
    from .models import MovimentacaoEstoque, ItemEstoque
    mov_id = request.POST.get('id')
    try:
        mov = MovimentacaoEstoque.objects.get(id=mov_id)
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
# Decorators
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
# --- REGISTRAR PERDA DE ESTOQUE ---
@login_required
@require_POST
def registrar_perda(request):
    empresa = get_empresa_da_sessao(request)
    produto_id = request.POST.get('produto_id')
    quantidade = float(request.POST.get('quantidade', 0))
    from .models import Produto, ItemEstoque, MovimentacaoEstoque
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
        from datetime import date as dt_date
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

from .models import SubcategoriaProduto, Produto
# -----------------------------
# API: Subcategorias e Produtos de Matéria-Prima
# -----------------------------
from django.views.decorators.http import require_GET

@login_required
@require_GET
def listar_materias_primas_por_subcategoria(request):
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
        from datetime import date as dt_date
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
    empresa = get_empresa_da_sessao(request)
    from .models import CategoriaProduto, SubcategoriaProduto
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
    from datetime import date as dt_date
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
        item_estoque.quantidade = float(item_estoque.quantidade) + qtd
        if preco > 0:
            item_estoque.preco_custo = preco
        item_estoque.save()
        MovimentacaoEstoque.objects.create(
            item=item_estoque,
            tipo='entrada',
            quantidade=qtd,
            data=data,
            observacao=f'Entrada Comercial #{entrada.id}' + (f' - {fornecedor.nome}' if fornecedor else ''),
            criado_por=request.user,
        )
    return JsonResponse({'status': 'ok'})


@login_required
def detalhe_entrada_comercial(request, id):
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

    from datetime import date as dt_date
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
    empresa = get_empresa_da_sessao(request)
    data_ini = request.GET.get('data_ini', '')
    data_fim = request.GET.get('data_fim', '')
    fornecedor_id = request.GET.get('fornecedor_id', '')

    from datetime import date as dt_date
    from django.db.models import Sum, Count

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
    from .models import ItemEntradaComercial
    resultado = []
    fornecedores_ids = entradas.values_list('fornecedor_id', flat=True).distinct()
    for forn_id in fornecedores_ids:
        ents = entradas.filter(fornecedor_id=forn_id)
        itens = ItemEntradaComercial.objects.filter(entrada__in=ents)
        valor_total = sum(float(i.quantidade) * float(i.preco_unitario) for i in itens)
        qtd_total = sum(float(i.quantidade) for i in itens)
        if forn_id:
            try:
                forn = Fornecedor.objects.get(id=forn_id)
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
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    empresa = get_empresa_da_sessao(request)
    f = get_object_or_404(Fornecedor, id=id, empresa=empresa)
    f.delete()
    return JsonResponse({'status': 'ok'})


@login_required
def _aplicar_classes_senha(form):
    attrs = {'class': 'form-control', 'autocomplete': 'off'}
    form.fields['old_password'].widget.attrs.update(attrs)
    form.fields['new_password1'].widget.attrs.update(attrs)
    form.fields['new_password2'].widget.attrs.update(attrs)
    return form

@login_required
def perfil(request):
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
    return render(request, 'documentacao.html')

