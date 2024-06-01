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
            cache Bool DEFAULT FALSE 
        )
    ''')

    # Commit the changes
    conn.commit()


# CRUD Operations

# Create
async def create_Url(id, path, signature, method, cache):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = f'INSERT INTO Urls (id, path, signature, method, cache) VALUES ("{id}", "{path}", "{signature}", "{method}", "{cache}")'
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
        return {"id": result[0], "path": result[1], "signature": result[2], "method": result[3], "cache": result[4], }
    return None


# Update
async def update_Url(id, path, signature, method, cache):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = 'UPDATE Urls SET path=?, signature=?, method=?, cache=? WHERE id=?'
    cursor.execute(query, (path, signature, method, cache, id))
    connection.commit()


# Delete
async def delete_url(id):
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object to execute SQL commands
    cursor = connection.cursor()
    query = 'DELETE FROM Urls WHERE id=?'
    cursor.execute(query, (id,))
    connection.commit()
