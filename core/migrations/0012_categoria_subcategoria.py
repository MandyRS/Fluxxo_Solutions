from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_produto_subcategoria"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoriaProduto",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("descricao", models.CharField(blank=True, max_length=255, null=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.empresa")),
            ],
            options={
                "unique_together": {("empresa", "nome")},
                "verbose_name": "Categoria de Produto",
                "verbose_name_plural": "Categorias de Produto",
            },
        ),
        migrations.CreateModel(
            name="SubcategoriaProduto",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("descricao", models.CharField(blank=True, max_length=255, null=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.empresa")),
                ("categoria", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subcategorias", to="core.categoriaproduto")),
            ],
            options={
                "unique_together": {("empresa", "categoria", "nome")},
                "verbose_name": "Subcategoria de Produto",
                "verbose_name_plural": "Subcategorias de Produto",
            },
        ),
    ]
