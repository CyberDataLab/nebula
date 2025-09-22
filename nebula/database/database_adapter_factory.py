from nebula.database.adapters.postgress.postgress import PostgresDB
from nebula.database.database_adapter_interface import DatabaseAdapter

class DatabaseAdapterException(Exception):
    pass

def factory_database_adapter(database_adapter: str) -> DatabaseAdapter:

    ADAPTERS = {
        "PostgresDB": PostgresDB
    }

    db_adapter = ADAPTERS.get(database_adapter, None)
    if db_adapter:
        return db_adapter()
    else:
        raise DatabaseAdapterException(f"Database Adapter \"{database_adapter}\" not supported")
