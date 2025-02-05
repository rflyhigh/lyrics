from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import time
import threading
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from contextlib import contextmanager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Database connection context manager
@contextmanager
def get_db_connection():
    conn = sqlite3.connect('documents.db')
    try:
        yield conn
    finally:
        conn.close()

# Database initialization
def init_db():
    try:
        with get_db_connection() as conn:
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
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

def generate_id(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_delete_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# Keep-alive mechanism
def keep_alive():
    while True:
        logger.info("Keep-alive ping")
        time.sleep(300)

@app.route('/publish', methods=['POST'])
def publish_document():
    try:
        data = request.json
        doc_id = generate_id()
        delete_code = generate_delete_code()
        
        with get_db_connection() as conn:
            c = conn.cursor()
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
        logger.error(f"Error publishing document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/document/<doc_id>', methods=['GET'])
def get_document(doc_id):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
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
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
    except Exception as e:
        logger.error(f"Error retrieving document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/delete/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    delete_code = request.args.get('code')
    
    if not delete_code:
        return jsonify({
            'success': False,
            'error': 'Delete code required'
        }), 400
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
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
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def cleanup_old_documents():
    while True:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                threshold = datetime.now() - timedelta(days=30)
                c.execute('DELETE FROM documents WHERE created_at < ?', (threshold,))
                conn.commit()
                logger.info("Completed cleanup of old documents")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            time.sleep(86400)

if __name__ == '__main__':
    try:
        init_db()
        # Start background threads
        threading.Thread(target=keep_alive, daemon=True).start()
        threading.Thread(target=cleanup_old_documents, daemon=True).start()
        
        # Get port from environment variable or use default
        port = int(os.getenv('PORT', 5000))
        
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
