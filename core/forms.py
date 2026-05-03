from django import forms
from .models import Orcamento, ItemOrcamento, Empresa, MovimentacaoEstoque

class OrcamentoForm(forms.ModelForm):
    class Meta:
        model = Orcamento
        fields = [
            'cliente', 'previsao_entrega', 'solicitante', 'escopo',
            'local_uso', 'responsavel', 'observacao',
            'forma_pagamento', 'vencimento', 'desconto'
        ]
        widgets = {
            'previsao_entrega': forms.DateInput(attrs={'type': 'date'}),
            'vencimento': forms.DateInput(attrs={'type': 'date'}),
            'desconto': forms.NumberInput(attrs={'step': '0.01'}),
        }

class ItemOrcamentoForm(forms.ModelForm):
    class Meta:
        model = ItemOrcamento
        fields = ['produto', 'servico', 'quantidade', 'preco_unitario']

    def clean(self):
        cleaned_data = super().clean()
        produto = cleaned_data.get('produto')
        servico = cleaned_data.get('servico')
        if not produto and not servico:
            raise forms.ValidationError("Informe o produto ou o serviço.")
        if produto and servico:
            raise forms.ValidationError("Informe somente produto ou serviço, não ambos.")
        return cleaned_data


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['nome', 'cnpj', 'telefone', 'endereco', 'logo']


# ------------------------
# FLUXO BANCÁRIO
# ------------------------
from .models import Banco, LancamentoBancario

class BancoForm(forms.ModelForm):
    class Meta:
        model = Banco
        fields = ['nome', 'agencia', 'conta', 'saldo_inicial']


class LancamentoBancarioForm(forms.ModelForm):
    class Meta:
        model = LancamentoBancario
        fields = ['data', 'descricao', 'valor', 'tipo', 'categoria', 'banco']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }

class MovimentacaoEstoqueForm(forms.ModelForm):
    class Meta:
        model = MovimentacaoEstoque
        fields = ['quantidade', 'data', 'observacao']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}),
            'quantidade': forms.NumberInput(attrs={'step': '0.01'}),
            'observacao': forms.TextInput(),
        }
