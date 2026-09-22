"""Shared Alembic environment builder.

Each service gets its own migration history in its own schema, with its own
`alembic_version` table — that independence is the point of the split, so the
only thing shared is this boilerplate.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text


def run(target_metadata, schema: str, database_url: str) -> None:
    config = context.config
    config.set_main_option("sqlalchemy.url", database_url)

    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

    def include_object(obj, name, type_, reflected, compare_to):
        # Never let one service's autogenerate try to drop another's tables.
        if type_ == "table":
            return obj.schema == schema
        return True

    if context.is_offline_mode():
        context.configure(
            url=database_url,
            target_metadata=target_metadata,
            literal_binds=True,
            include_schemas=True,
            include_object=include_object,
            version_table_schema=schema,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema=schema,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
