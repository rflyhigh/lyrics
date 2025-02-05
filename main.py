from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import time
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Database initialization
def init_db():
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents
        (id TEXT PRIMARY KEY,
         delete_code TEXT,
         title TEXT,
         author TEXT,
         content TEXT,
         font_size TEXT,
         text_color TEXT,
         text_format TEXT,
         line_height TEXT,
         theme TEXT,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    conn.commit()
    conn.close()

# Generate random ID and delete code
def generate_id(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# Keep-alive mechanism
def keep_alive():
    while True:
        print("Keep-alive ping")
        time.sleep(300)  # Ping every 5 minutes

# Start keep-alive thread
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()

@app.route('/publish', methods=['POST'])
def publish_document():
    data = request.json
    
    # Generate unique ID and delete code
    doc_id = generate_id()
    delete_code = generate_delete_code()
    
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()
    
    try:
        c.execute('''
            INSERT INTO documents 
            (id, delete_code, title, author, content, font_size, text_color, 
             text_format, line_height, theme)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            doc_id,
            delete_code,
            data.get('title'),
            data.get('author'),
            data.get('content'),
            data.get('fontSize'),
            data.get('textColor'),
            data.get('textFormat'),
            data.get('lineHeight'),
            data.get('theme')
        ))
        
        conn.commit()
        return jsonify({
            'success': True,
            'id': doc_id,
            'delete_code': delete_code
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        conn.close()

@app.route('/document/<doc_id>', methods=['GET'])
def get_document(doc_id):
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT * FROM documents WHERE id = ?', (doc_id,))
        doc = c.fetchone()
        
        if doc:
            return jsonify({
                'success': True,
                'document': {
                    'title': doc[2],
                    'author': doc[3],
                    'content': doc[4],
                    'fontSize': doc[5],
                    'textColor': doc[6],
                    'textFormat': doc[7],
                    'lineHeight': doc[8],
                    'theme': doc[9]
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
    finally:
        conn.close()

@app.route('/delete/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({
            'success': False,
            'error': 'Delete code required'
        }), 400
    
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT delete_code FROM documents WHERE id = ?', (doc_id,))
        stored_code = c.fetchone()
        
        if not stored_code:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
        
        if stored_code[0] != delete_code:
            return jsonify({
                'success': False,
                'error': 'Invalid delete code'
            }), 403
        
        c.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.commit()
        
        return jsonify({
            'success': True
        })
    finally:
        conn.close()

# Cleanup old documents (run periodically)
def cleanup_old_documents():
    while True:
        conn = sqlite3.connect('documents.db')
        c = conn.cursor()
        
        # Delete documents older than 30 days
        threshold = datetime.now() - timedelta(days=30)
        c.execute('DELETE FROM documents WHERE created_at < ?', (threshold,))
        conn.commit()
        conn.close()
        
        time.sleep(86400)  # Run once per day

cleanup_thread = threading.Thread(target=cleanup_old_documents, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
