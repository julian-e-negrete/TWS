from config import host, user, password, database


import mysql.connector

# Establish connection to the MySQL database
connection = mysql.connector.connect(
    host=host,
    user=user,
    password=password,
    database=database
)

# Create a cursor object using the connection
cursor = connection.cursor()

# Example query: fetch all records from a table
cursor.execute("SELECT * FROM ADR_RATIO")

# Fetch and print results
result = cursor.fetchall()
for row in result:
    print(row)

# Close the cursor and connection
cursor.close()
connection.close()
