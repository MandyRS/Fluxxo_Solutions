from django.contrib import admin
from .models import (
    Empresa,
    UserEmpresa,
    Produto,
    Cliente,
    Servico,
    Orcamento,
    ItemOrcamento
)

# ------------------------
# EMPRESA
# ------------------------
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cnpj', 'telefone', 'endereco')
    search_fields = ('nome', 'cnpj')
    list_per_page = 20


# ------------------------
# RELAÇÃO USUÁRIO X EMPRESA
# ------------------------
@admin.register(UserEmpresa)
class UserEmpresaAdmin(admin.ModelAdmin):
    list_display = ('user', 'empresa')
    list_filter = ('empresa',)
    search_fields = ('user__username', 'empresa__nome')


# ------------------------
# PRODUTOS
# ------------------------
@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'codigo', 'empresa', 'categoria', 'subcategoria', 'preco')
    list_filter = ('empresa', 'categoria', 'subcategoria')
    search_fields = ('nome', 'codigo', 'empresa__nome', 'subcategoria')
    list_editable = ('preco',)
    list_per_page = 20


# ------------------------
# CLIENTES
# ------------------------
@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('razao_social', 'nome_fantasia', 'empresa', 'cpf_cnpj', 'telefone', 'email')
    list_filter = ('empresa',)
    search_fields = ('razao_social', 'nome_fantasia', 'cpf_cnpj', 'email')
    list_per_page = 20


# ------------------------
# SERVIÇOS
# ------------------------
@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'codigo', 'empresa', 'preco')
    list_filter = ('empresa',)
    search_fields = ('nome', 'codigo', 'empresa__nome')
    list_editable = ('preco',)
    list_per_page = 20


# ------------------------
# ITENS DO ORÇAMENTO (INLINE)
# ------------------------
class ItemOrcamentoInline(admin.TabularInline):
    model = ItemOrcamento
    extra = 1
    autocomplete_fields = ('produto', 'servico')
    readonly_fields = ('total',)
    fields = ('produto', 'servico', 'quantidade', 'preco_unitario', 'total')


# ------------------------
# ORÇAMENTO
# ------------------------
@admin.register(Orcamento)
class OrcamentoAdmin(admin.ModelAdmin):
    list_display = ('numero', 'cliente', 'empresa', 'usuario', 'criado_em', 'total')
    list_filter = ('empresa', 'usuario', 'cliente')
    search_fields = ('numero', 'cliente__razao_social', 'usuario__username')
    readonly_fields = ('subtotal', 'total', 'criado_em')
    inlines = [ItemOrcamentoInline]
    date_hierarchy = 'criado_em'
    ordering = ('-criado_em',)

    fieldsets = (
        ('Informações Básicas', {
            'fields': ('empresa', 'usuario', 'numero', 'cliente', 'criado_em')
        }),
        ('Detalhes do Orçamento', {
            'fields': (
                'solicitante', 'previsao_entrega', 'servicos_descricao',
                'escopo', 'local_uso', 'responsavel', 'observacao'
            )
        }),
        ('Pagamento', {
            'fields': ('forma_pagamento', 'vencimento', 'desconto')
        }),
        ('Totais', {
            'fields': ('subtotal', 'total'),
        }),
    )


# ------------------------
# ITEM DO ORÇAMENTO (ISOLADO)
# ------------------------
@admin.register(ItemOrcamento)
class ItemOrcamentoAdmin(admin.ModelAdmin):
    list_display = ('orcamento', 'produto', 'servico', 'quantidade', 'preco_unitario', 'total')
    search_fields = ('orcamento__numero', 'produto__nome', 'servico__nome')
    list_filter = ('orcamento__empresa',)
