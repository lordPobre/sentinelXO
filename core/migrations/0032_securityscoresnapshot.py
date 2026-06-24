"""
Migración idempotente para SecurityScoreSnapshot.

⚠️ ANTES DE USAR:
  1. Renombra este archivo a core/migrations/00XX_securityscoresnapshot.py
     usando el NÚMERO siguiente al de tu última migración de core
     (ej. si la última es 0031_xxx.py → este sería 0032_securityscoresnapshot.py).
  2. En `dependencies`, reemplaza "REEMPLAZAR_POR_TU_ULTIMA_MIGRACION" por el
     nombre (sin .py) de tu última migración de core.

El patrón CreateModelIfNotExists evita el DuplicateTable cuando los 3 servicios
de Railway (web/worker/beat) corren `migrate` en paralelo: si la tabla ya
existe, la operación se omite (la tabla y su índice se crean juntos).
"""
from django.db import migrations, models
import django.db.models.deletion


class CreateModelIfNotExists(migrations.CreateModel):
    """CreateModel que no falla si la tabla ya existe."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        table = model._meta.db_table
        if table in schema_editor.connection.introspection.table_names():
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_alter_client_options"),
    ]

    operations = [
        CreateModelIfNotExists(
            name="SecurityScoreSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.IntegerField(default=0, verbose_name="Puntaje")),
                ("grade", models.CharField(default="F", max_length=1, verbose_name="Letra")),
                ("breakdown", models.JSONField(blank=True, default=list, verbose_name="Desglose por dimensión")),
                ("findings", models.JSONField(blank=True, default=list, verbose_name="Hallazgos")),
                ("computed_at", models.DateTimeField(auto_now_add=True, verbose_name="Calculado")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="security_scores", to="core.client",
                                             verbose_name="Cliente")),
            ],
            options={
                "verbose_name": "Score de seguridad",
                "verbose_name_plural": "Scores de seguridad",
                "ordering": ["-computed_at"],
                "indexes": [models.Index(fields=["client", "-computed_at"], name="core_secsco_cli_idx")],
            },
        ),
    ]
