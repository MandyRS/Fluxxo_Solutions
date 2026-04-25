from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_remove_produto_limite_alto_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="produto",
            name="subcategoria",
            field=models.CharField(max_length=50, blank=True, null=True, help_text="Subcategoria do produto dentro da categoria."),
        ),
    ]
