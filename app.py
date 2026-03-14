import os
import sqlite3
import shutil
import uuid
import re
import stat
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
USER_QUOTA = 10 * 1024 * 1024 * 1024

DATA_DIR = 'data'
UPLOAD_DIR = 'uploads'
USER_DB = os.path.join(DATA_DIR, 'user.db')
KEY_DB = os.path.join(DATA_DIR, 'key.db')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def remove_readonly(func, path, _):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

def init_dbs():
    conn_user = sqlite3.connect(USER_DB)
    conn_user.execute('''CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        password TEXT,
                        auth_key TEXT,
                        quota INTEGER DEFAULT 10737418240
                    )''')
    try:
        conn_user.execute('ALTER TABLE users ADD COLUMN quota INTEGER DEFAULT 10737418240')
    except sqlite3.OperationalError:
        pass

    conn_user.execute('''CREATE TABLE IF NOT EXISTS files (
                        user_id TEXT,
                        filename TEXT,
                        is_important INTEGER DEFAULT 0,
                        is_trashed INTEGER DEFAULT 0,
                        trash_date TEXT,
                        trash_expiry_days INTEGER DEFAULT 1,
                        last_accessed TEXT,
                        PRIMARY KEY (user_id, filename)
                    )''')
    conn_user.commit()
    conn_user.close()

    conn_key = sqlite3.connect(KEY_DB)
    conn_key.execute('''CREATE TABLE IF NOT EXISTS keys (
                        auth_key TEXT PRIMARY KEY,
                        memo TEXT,
                        is_used INTEGER DEFAULT 0,
                        linked_user TEXT
                    )''')
    conn_key.commit()
    conn_key.close()

init_dbs()

def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_id') != 'admin':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_dir_size(path):
    total = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if not d.startswith('.deleted_')]
            for f in filenames:
                if f.startswith('.deleted_'):
                    continue
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
    return total

def cleanup_trash(user_id):
    conn = get_db(USER_DB)
    trashed_files = conn.execute('SELECT * FROM files WHERE user_id = ? AND is_trashed = 1', (user_id,)).fetchall()
    now = datetime.now()
    
    for f in trashed_files:
        if f['trash_date']:
            t_date = datetime.strptime(f['trash_date'], '%Y-%m-%d %H:%M:%S')
            expiry_days = f['trash_expiry_days']
            if now > t_date + timedelta(days=expiry_days):
                original_target = os.path.join(UPLOAD_DIR, user_id, f['filename'])
                target_path = original_target
                
                if os.path.exists(target_path):
                    del_name = f".deleted_{uuid.uuid4().hex}"
                    del_path = os.path.join(os.path.dirname(target_path), del_name)
                    try:
                        os.rename(target_path, del_path)
                        target_path = del_path
                    except OSError:
                        pass
                        
                    if os.path.isdir(target_path):
                        shutil.rmtree(target_path, onerror=remove_readonly)
                    else:
                        try:
                            os.chmod(target_path, stat.S_IWRITE)
                            os.remove(target_path)
                        except OSError:
                            pass
                
                if not os.path.exists(original_target):
                    conn.execute('DELETE FROM files WHERE user_id = ? AND (filename = ? OR filename LIKE ?)', (user_id, f['filename'], f['filename'] + '/%'))
    
    conn.commit()
    conn.close()

def get_safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def secure_path(path):
    parts = path.replace('\\', '/').split('/')
    safe_parts = [get_safe_name(p) for p in parts if p and p not in ('.', '..')]
    return '/'.join(safe_parts)

@app.route('/')
@login_required
def index():
    if session.get('user_id') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session.permanent = True
        user_id = request.form['user_id']
        password = request.form['password']
        if user_id == 'muel2962' and password == '!samuel0602!':
            session['user_id'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        conn = get_db(USER_DB)
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('index'))
        return render_template('login.html', error="아이디 또는 비밀번호가 잘못되었습니다.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form['user_id']
        name = request.form['name']
        password = request.form['password']
        auth_key = request.form['auth_key']
        conn_key = get_db(KEY_DB)
        key_record = conn_key.execute('SELECT * FROM keys WHERE auth_key = ? AND is_used = 0', (auth_key,)).fetchone()
        if not key_record:
            conn_key.close()
            return render_template('register.html', error="유효하지 않거나 이미 사용된 인증키입니다.")
        conn_user = get_db(USER_DB)
        existing_user = conn_user.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if existing_user:
            conn_user.close()
            conn_key.close()
            return render_template('register.html', error="이미 존재하는 아이디입니다.")
        hashed_pw = generate_password_hash(password)
        conn_user.execute('INSERT INTO users (id, name, password, auth_key) VALUES (?, ?, ?, ?)', 
                          (user_id, name, hashed_pw, auth_key))
        conn_user.commit()
        conn_user.close()
        conn_key.execute('UPDATE keys SET is_used = 1, linked_user = ? WHERE auth_key = ?', (user_id, auth_key))
        conn_key.commit()
        conn_key.close()
        os.makedirs(os.path.join(UPLOAD_DIR, user_id), exist_ok=True)
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    conn_key = get_db(KEY_DB)
    conn_user = get_db(USER_DB)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            memo = request.form.get('memo')
            new_key = str(uuid.uuid4())
            conn_key.execute('INSERT INTO keys (auth_key, memo) VALUES (?, ?)', (new_key, memo))
            conn_key.commit()
        elif action == 'delete':
            target_key = request.form.get('auth_key')
            key_info = conn_key.execute('SELECT linked_user FROM keys WHERE auth_key = ?', (target_key,)).fetchone()
            if key_info and key_info['linked_user']:
                target_user = key_info['linked_user']
                conn_user.execute('DELETE FROM users WHERE id = ?', (target_user,))
                conn_user.execute('DELETE FROM files WHERE user_id = ?', (target_user,))
                conn_user.commit()
                user_folder = os.path.join(UPLOAD_DIR, target_user)
                if os.path.exists(user_folder):
                    shutil.rmtree(user_folder, onerror=remove_readonly)
            conn_key.execute('DELETE FROM keys WHERE auth_key = ?', (target_key,))
            conn_key.commit()
        elif action == 'update_quota':
            target_user = request.form.get('user_id')
            new_quota_gb = float(request.form.get('quota_gb', 10))
            new_quota_bytes = int(new_quota_gb * 1024 * 1024 * 1024)
            conn_user.execute('UPDATE users SET quota = ? WHERE id = ?', (new_quota_bytes, target_user))
            conn_user.commit()
            
        conn_key.close()
        conn_user.close()
        return redirect(url_for('admin_dashboard'))
            
    keys = conn_key.execute('SELECT * FROM keys').fetchall()
    users = conn_user.execute('SELECT id, name, quota FROM users').fetchall()
    conn_key.close()
    conn_user.close()
    return render_template('admin.html', keys=keys, users=users)

@app.route('/api/files')
@login_required
def list_files():
    user_id = session['user_id']
    category = request.args.get('category', 'home')
    req_path = request.args.get('path', '')
    cleanup_trash(user_id)
    
    conn = get_db(USER_DB)
    db_files = {row['filename']: dict(row) for row in conn.execute('SELECT * FROM files WHERE user_id = ?', (user_id,)).fetchall()}
    conn.close()

    user_root = os.path.join(UPLOAD_DIR, user_id)
    safe_req_path = secure_path(req_path)
    current_dir = os.path.join(user_root, safe_req_path)
    
    files_data = []

    if category == 'home':
        if os.path.exists(current_dir):
            for item in os.listdir(current_dir):
                if item.startswith('.deleted_'):
                    continue
                item_path = os.path.join(current_dir, item)
                rel_path = os.path.join(safe_req_path, item).replace('\\', '/')
                meta = db_files.get(rel_path, {})
                is_trashed = bool(meta.get('is_trashed', 0))
                
                if is_trashed: continue

                if os.path.isdir(item_path):
                    files_data.append({
                        "name": item,
                        "type": "folder",
                        "path": rel_path,
                        "size": get_dir_size(item_path),
                        "url": "",
                        "is_important": bool(meta.get('is_important', 0)),
                        "is_trashed": False,
                        "last_accessed": meta.get('last_accessed', '1970-01-01 00:00:00')
                    })
                else:
                    files_data.append({
                        "name": item,
                        "type": "file",
                        "path": rel_path,
                        "size": os.path.getsize(item_path),
                        "url": f"/api/file/{rel_path}",
                        "is_important": bool(meta.get('is_important', 0)),
                        "is_trashed": False,
                        "last_accessed": meta.get('last_accessed', '1970-01-01 00:00:00')
                    })
    elif category == 'trash':
        trashed_items = {rel: meta for rel, meta in db_files.items() if meta.get('is_trashed', 0)}
        
        if safe_req_path == '':
            top_trashed = set()
            for rel in trashed_items:
                parts = rel.split('/')
                current_ancestor = ''
                for part in parts:
                    current_ancestor = f"{current_ancestor}/{part}" if current_ancestor else part
                    if current_ancestor in trashed_items:
                        top_trashed.add(current_ancestor)
                        break
            
            for item_path in top_trashed:
                meta = trashed_items[item_path]
                full_path = os.path.join(user_root, item_path)
                item_type = "folder" if os.path.isdir(full_path) else "file"
                files_data.append({
                    "name": os.path.basename(item_path),
                    "type": item_type,
                    "path": item_path,
                    "size": get_dir_size(full_path) if item_type == "folder" else (os.path.getsize(full_path) if os.path.exists(full_path) else 0),
                    "url": "" if item_type == "folder" else f"/api/file/{item_path}",
                    "is_important": bool(meta.get('is_important', 0)),
                    "is_trashed": True,
                    "last_accessed": meta.get('last_accessed', '1970-01-01 00:00:00')
                })
        else:
            for rel_path, meta in trashed_items.items():
                if os.path.dirname(rel_path).replace('\\', '/') == safe_req_path:
                    full_path = os.path.join(user_root, rel_path)
                    item_type = "folder" if os.path.isdir(full_path) else "file"
                    files_data.append({
                        "name": os.path.basename(rel_path),
                        "type": item_type,
                        "path": rel_path,
                        "size": get_dir_size(full_path) if item_type == "folder" else (os.path.getsize(full_path) if os.path.exists(full_path) else 0),
                        "url": "" if item_type == "folder" else f"/api/file/{rel_path}",
                        "is_important": bool(meta.get('is_important', 0)),
                        "is_trashed": True,
                        "last_accessed": meta.get('last_accessed', '1970-01-01 00:00:00')
                    })
    else:
        for rel_path, meta in db_files.items():
            item_path = os.path.join(user_root, rel_path)
            if os.path.exists(item_path):
                is_trashed = bool(meta.get('is_trashed', 0))
                is_important = bool(meta.get('is_important', 0))
                last_accessed = meta.get('last_accessed', '1970-01-01 00:00:00')

                if category == 'important' and (not is_important or is_trashed): continue

                item_type = "folder" if os.path.isdir(item_path) else "file"
                
                files_data.append({
                    "name": os.path.basename(rel_path),
                    "type": item_type,
                    "path": rel_path,
                    "size": get_dir_size(item_path) if item_type == "folder" else os.path.getsize(item_path),
                    "url": "" if item_type == "folder" else f"/api/file/{rel_path}",
                    "is_important": is_important,
                    "is_trashed": is_trashed,
                    "last_accessed": last_accessed
                })

    if category == 'recent':
        files_data = [f for f in files_data if not f['is_trashed'] and f['type'] == 'file']
        files_data.sort(key=lambda x: x['last_accessed'], reverse=True)
        files_data = files_data[:20]

    return jsonify(files_data)

@app.route('/api/file/action', methods=['POST'])
@login_required
def file_action():
    user_id = session['user_id']
    data = request.json
    action = data.get('action')
    filename = data.get('filename')
    
    conn = get_db(USER_DB)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if action == 'toggle_star':
        current = conn.execute('SELECT is_important FROM files WHERE user_id = ? AND filename = ?', (user_id, filename)).fetchone()
        new_val = 0 if current and current['is_important'] else 1
        conn.execute('INSERT OR IGNORE INTO files (user_id, filename) VALUES (?, ?)', (user_id, filename))
        conn.execute('UPDATE files SET is_important = ? WHERE user_id = ? AND filename = ?', (new_val, user_id, filename))
    
    elif action == 'trash':
        expiry = data.get('expiry', 1)
        conn.execute('INSERT OR IGNORE INTO files (user_id, filename) VALUES (?, ?)', (user_id, filename))
        conn.execute('UPDATE files SET is_trashed = 1, trash_date = ?, trash_expiry_days = ? WHERE user_id = ? AND (filename = ? OR filename LIKE ?)', (now, expiry, user_id, filename, filename + '/%'))
    
    elif action == 'restore':
        conn.execute('UPDATE files SET is_trashed = 0 WHERE user_id = ? AND (filename = ? OR filename LIKE ?)', (user_id, filename, filename + '/%'))
    
    elif action == 'delete_permanent':
        original_target = os.path.join(UPLOAD_DIR, user_id, filename)
        target_path = original_target
        
        if os.path.exists(target_path):
            del_name = f".deleted_{uuid.uuid4().hex}"
            del_path = os.path.join(os.path.dirname(target_path), del_name)
            try:
                os.rename(target_path, del_path)
                target_path = del_path
            except OSError:
                pass

            if os.path.isdir(target_path):
                shutil.rmtree(target_path, onerror=remove_readonly)
            else:
                try:
                    os.chmod(target_path, stat.S_IWRITE)
                    os.remove(target_path)
                except OSError:
                    pass
        
        if not os.path.exists(original_target):
            conn.execute('DELETE FROM files WHERE user_id = ? AND (filename = ? OR filename LIKE ?)', (user_id, filename, filename + '/%'))
        
        try:
            parent_dir = os.path.dirname(original_target)
            while parent_dir and parent_dir != os.path.join(UPLOAD_DIR, user_id):
                if not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
                else:
                    break
                parent_dir = os.path.dirname(parent_dir)
        except OSError:
            pass

    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_files():
    if 'files' not in request.files:
        return jsonify({"error": "No file received"}), 400
    
    files = request.files.getlist('files')
    paths = request.form.getlist('paths')
    if not paths:
        paths = [file.filename for file in files]

    user_id = session['user_id']
    
    conn = get_db(USER_DB)
    user = conn.execute('SELECT quota FROM users WHERE id = ?', (user_id,)).fetchone()
    user_quota = user['quota'] if user else USER_QUOTA
    
    user_folder = os.path.join(UPLOAD_DIR, user_id)
    current_used = get_dir_size(user_folder)
    
    total_upload_size = 0
    for file in files:
        file.seek(0, os.SEEK_END)
        total_upload_size += file.tell()
        file.seek(0)
        
    if current_used + total_upload_size > user_quota:
        conn.close()
        return jsonify({"error": "할당된 용량을 초과했습니다."}), 403

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for file, path in zip(files, paths):
        if file.filename == '': continue
        safe_path = secure_path(path)
        if not safe_path: continue

        full_save_path = os.path.join(user_folder, safe_path)
        os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
        file.save(full_save_path)
        
        conn.execute('INSERT OR REPLACE INTO files (user_id, filename, last_accessed) VALUES (?, ?, ?)', (user_id, safe_path, now))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/file/<path:filename>')
@login_required
def serve_file(filename):
    user_id = session['user_id']
    conn = get_db(USER_DB)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('INSERT OR IGNORE INTO files (user_id, filename) VALUES (?, ?)', (user_id, filename))
    conn.execute('UPDATE files SET last_accessed = ? WHERE user_id = ? AND filename = ?', (now, user_id, filename))
    conn.commit()
    conn.close()
    return send_from_directory(os.path.join(UPLOAD_DIR, user_id), filename)

@app.route('/api/quota')
@login_required
def check_quota():
    user_id = session['user_id']
    
    conn = get_db(USER_DB)
    user = conn.execute('SELECT quota FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    user_quota = user['quota'] if user else USER_QUOTA
    user_folder = os.path.join(UPLOAD_DIR, user_id)
    used = get_dir_size(user_folder)
    
    return jsonify({
        "used": used,
        "total": user_quota,
        "percent": min((used / user_quota) * 100, 100) if user_quota > 0 else 100
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)