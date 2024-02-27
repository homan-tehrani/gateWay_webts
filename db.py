import sqlite3

# Connect to SQLite database (or create a new one if it doesn't exist)
conn = sqlite3.connect('urls.db')

# Create a cursor object to execute SQL commands
cursor = conn.cursor()

# Create a table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS URLS (
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
def create_user(path, signature, method, cache):
    cursor.execute('INSERT INTO URLS (path,signature,method, cache) VALUES (?,?,?, ?)',
                   (path, signature, method, cache))
    conn.commit()


# Read
def get_urls():
    cursor.execute('SELECT * FROM URLS')
    return cursor.fetchall()


# Read
def get_url(signature):
    cursor.execute('SELECT * FROM URLS WHERE  signature=?', (signature,))
    result = cursor.fetchone()
    if result:
        print('[[[[[[pppppppppppp')
        return {"id": result[0], "path": result[1],"signature": result[2], "method": result[3], "cache": result[4], }
    return None


# Update
def update_user(user_id, new_email):
    cursor.execute('UPDATE URLS SET email=? WHERE id=?', (new_email, user_id))
    conn.commit()


# Delete
def delete_user(user_id):
    cursor.execute('DELETE FROM URLS WHERE id=?', (user_id,))
    conn.commit()


print(']===================================')
# create_user("https://abstinence12.sirafgroup.com/v1/leaveSin/UserLeaveSinAdminApi/getStatisticsAdmin/",
#             '/v1/leaveSin/UserLeaveSinAdminApi/getStatisticsAdmin/', 'get', True)
