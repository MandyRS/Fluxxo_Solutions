

from django.db import models
from datetime import date
from django.contrib.auth.models import User

# ------------------------
# FICHA TÉCNICA (BOM)
# ------------------------

class ProdutoMateriaPrima(models.Model):
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE)
    produto_final = models.ForeignKey('Produto', on_delete=models.CASCADE, related_name='materias_primas')
    materia_prima = models.ForeignKey('Produto', on_delete=models.CASCADE, related_name='usado_em')
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ('empresa', 'produto_final', 'materia_prima')

    def __str__(self):
        return f"{self.produto_final.nome} -> {self.materia_prima.nome} ({self.quantidade})"

# ------------------------
# EMPRESA
# ------------------------
class Empresa(models.Model):
    nome = models.CharField(max_length=150)
    cnpj = models.CharField(max_length=20, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)

    def __str__(self):
        return self.nome


# ------------------------
# RELAÇÃO USUÁRIO X EMPRESA
# ------------------------
class UserEmpresa(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'empresa')
        verbose_name = "Usuário da Empresa"
        verbose_name_plural = "Usuários da Empresa"

    def __str__(self):
        return f"{self.user.username} - {self.empresa.nome}"


# ------------------------
# PRODUTOS
# ------------------------
class Produto(models.Model):
    CATEGORIA_CHOICES = [
        ('produto', 'Produto Final'),
        ('materia_prima', 'Matéria Prima'),
        ('embalagem', 'Embalagem'),
        ('tampa', 'Tampa'),
        ('rotulo', 'Rótulo'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=50, blank=True)
    nome = models.CharField(max_length=150)
    descricao = models.TextField(blank=True, null=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    peso = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    UNIDADE_CHOICES = [
        ('ml', 'ml'),
        ('l', 'L'),
        ('g', 'g'),
        ('kg', 'kg'),
        ('pct', 'pct'),
        ('un', 'un'),
        ('cx', 'cx'),
        ('outro', 'Outro'),
    ]
    unidade = models.CharField(max_length=20, choices=UNIDADE_CHOICES, default='un')
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default='produto')
    subcategoria = models.ForeignKey('SubcategoriaProduto', on_delete=models.SET_NULL, null=True, blank=True, related_name='produtos')

    def __str__(self):
        return f"{self.nome} ({self.empresa.nome})"


# ------------------------
# CLIENTES
# ------------------------
class Cliente(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    razao_social = models.CharField(max_length=200)
    nome_fantasia = models.CharField(max_length=200, blank=True)
    cpf_cnpj = models.CharField(max_length=50, blank=True)
    telefone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    cidade_uf = models.CharField(max_length=100, blank=True)
    cep = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.razao_social


# ------------------------
# SERVIÇOS
# ------------------------
class Servico(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    codigo = models.CharField(max_length=50, blank=True)
    nome = models.CharField(max_length=200)
    preco = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descricao = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.nome} ({self.empresa.nome})"


# ------------------------
# ORÇAMENTO (CABEÇALHO)
# ------------------------
class Orcamento(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    numero = models.PositiveIntegerField(editable=False, unique=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    previsao_entrega = models.DateField(null=True, blank=True)
    solicitante = models.CharField(max_length=200, blank=True)
    servicos_descricao = models.TextField(blank=True)
    escopo = models.TextField(blank=True)
    local_uso = models.CharField(max_length=255, blank=True)
    responsavel = models.CharField(max_length=200, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    observacao = models.TextField(blank=True)
    forma_pagamento = models.CharField(max_length=100, blank=True)
    vencimento = models.DateField(null=True, blank=True)
    desconto = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['-criado_em']

    @property
    def subtotal(self):
        return sum([it.quantidade * float(it.preco_unitario) for it in self.itens.all()])

    @property
    def total(self):
        return self.subtotal - float(self.desconto or 0)

    def save(self, *args, **kwargs):
        
        if not self.numero:
            ano = date.today().year
            ultimo = Orcamento.objects.filter(
                empresa=self.empresa,
                criado_em__year=ano
            ).order_by('-numero').first()
            self.numero = (ultimo.numero + 1) if ultimo else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Orçamento #{self.numero} - {self.cliente.razao_social}"


# ------------------------
# ITENS DO ORÇAMENTO
# ------------------------
class ItemOrcamento(models.Model):
    orcamento = models.ForeignKey(Orcamento, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, null=True, blank=True)
    servico = models.ForeignKey(Servico, on_delete=models.CASCADE, null=True, blank=True)
    quantidade = models.PositiveIntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total(self):
        return self.quantidade * self.preco_unitario

    def __str__(self):
        nome = self.produto.nome if self.produto else (self.servico.nome if self.servico else "Item")
        return f"{nome} x{self.quantidade}"


# ------------------------
# BANCOS E FLUXO BANCÁRIO
# ------------------------
class Banco(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    agencia = models.CharField(max_length=20, blank=True)
    conta = models.CharField(max_length=20, blank=True)
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.nome} ({self.empresa.nome})"


class LancamentoBancario(models.Model):
    TIPO_CHOICES = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
    ]
    CLASSIFICACAO_CHOICES = [
        ("despesa", "Despesa"),
        ("investimento", "Investimento"),
        ("adiantamento_socio", "Adiantamento de Sócio"),
        ("distribuicao_lucro", "Distribuição de Lucro"),
        ("outros", "Outros"),
    ]
    banco = models.ForeignKey(Banco, on_delete=models.CASCADE, related_name="lancamentos")
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    classificacao = models.CharField(max_length=30, choices=CLASSIFICACAO_CHOICES)
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.data} - {self.descricao} ({self.get_tipo_display()})"


# ------------------------
# ESTOQUE
# ------------------------
class ItemEstoque(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, null=True, blank=True)
    nome = models.CharField(max_length=200)
    codigo = models.CharField(max_length=50, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unidade = models.CharField(max_length=20, default='un')
    preco_custo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estoque_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.empresa.nome})"

    @property
    def abaixo_minimo(self):
        return self.quantidade < self.estoque_minimo


class MovimentacaoEstoque(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('saida', 'Saída'),
        ('ajuste', 'Ajuste'),
    ]
    item = models.ForeignKey(ItemEstoque, on_delete=models.CASCADE, related_name='movimentacoes')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    quantidade = models.DecimalField(max_digits=14, decimal_places=2)
    data = models.DateField()
    observacao = models.CharField(max_length=255, blank=True)
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.item.nome} ({self.quantidade})"
        
# ------------------------
from django.db import models
# CATEGORIAS E SUBCATEGORIAS DE PRODUTO
# ------------------------
class CategoriaProduto(models.Model):
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    descricao = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = ('empresa', 'nome')
        verbose_name = 'Categoria de Produto'
        verbose_name_plural = 'Categorias de Produto'

    def __str__(self):
        return self.nome

class SubcategoriaProduto(models.Model):
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE)
    categoria = models.ForeignKey(CategoriaProduto, on_delete=models.CASCADE, related_name='subcategorias')
    nome = models.CharField(max_length=100)
    descricao = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = ('empresa', 'categoria', 'nome')
        verbose_name = 'Subcategoria de Produto'
        verbose_name_plural = 'Subcategorias de Produto'

    def __str__(self):
        return f"{self.categoria.nome} - {self.nome}"