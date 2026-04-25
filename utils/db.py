import sqlite3

# from utils.global_variables import DB_NAME

DB_NAME = "Urls.db"

async def check_url_table_exists(table_name="Urls"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("table_name",))
    result = cursor.fetchone()
    if result is not None:
        return True
    else:
        await createDB()
        return True
    
async def createDB():
    # Connect to SQLite database (or create a new one if it doesn't exist)
    print("asfasdfasdf")
    conn = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = conn.cursor()

    # Create a table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Urls (
            id INTEGER PRIMARY KEY,
            path TEXT,
            signature TEXT,
            method TEXT,
            cache Bool DEFAULT FALSE ,
            project_id INTEGER  ,
            project_name TEXT 
        )
    ''')

    # Commit the changes
    conn.commit()


# CRUD Operations

# Create
async def create_Url(id, path, signature, method, cache, project_id, project_name):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = f'INSERT INTO Urls (id, path, signature, method, cache, project_id, project_name) VALUES ("{id}", "{path}", "{signature}", "{method}", "{cache}", "{project_id}", "{project_name}")'
    cursor.execute(query)
    connection.commit()


# Read
async def get_urls():
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands

    cursor = connection.cursor()
    cursor.execute('SELECT * FROM Urls')
    response = []
    results = cursor.fetchall()
    for result in results:
        response.append(
            {"id": result[0], "path": result[1], "signature": result[2], "method": result[3], "cache": result[4]})
    return response


# Read
async def get_url(id):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    if type(id) is int:
        cursor.execute('SELECT * FROM Urls WHERE  id=?', (id,))
    else:
        cursor.execute('SELECT * FROM Urls WHERE  signature=?', (id,))
    result = cursor.fetchone()

    if result:
        return {"id": result[0], "path": result[1], "signature": result[2], "method": result[3], "cache": result[4],"project_id": result[5], "project_name": result[6], }
    return None

async def get_route(signature: str, method: str):
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT * FROM Urls
        WHERE signature = ?
        AND method = ?
        LIMIT 1
        """,
        (signature, method.lower())
    )

    result = cursor.fetchone()
    connection.close()

    if not result:
        return None

    return {
        "id": result[0],
        "path": result[1],
        "signature": result[2],
        "method": result[3],
        "cache": result[4],
        "project_id": result[5],
        "project_name": result[6],
    }

# Update
async def update_Url(id, path, signature, method, cache, project_id, project_name):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = 'UPDATE Urls SET path=?, signature=?, method=?, cache=?, project_id=?, project_name=? WHERE id=?'
    cursor.execute(query, (path, signature, method, cache, project_id, project_name, id))
    connection.commit()


# Delete
async def delete_url(id):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = 'DELETE FROM Urls WHERE id=?'
    cursor.execute(query, (id,))
    connection.commit()
