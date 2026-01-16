"""
Сервер лицензий для MTA Light Generator
Автор: @mtashnik55
"""

import hashlib
import json
import sqlite3
import uuid
import functools
import base64
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, make_response
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()  # Генерируем случайный секретный ключ
CORS(app)  # Разрешаем CORS для локальных запросов

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Таблица лицензий
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT UNIQUE,
                  hardware_id TEXT UNIQUE,
                  client_name TEXT,
                  email TEXT,
                  phone TEXT,
                  created_date TEXT,
                  expiry_date TEXT,
                  is_active INTEGER DEFAULT 1,
                  notes TEXT)''')
    
    # Таблица админов
    c.execute('''CREATE TABLE IF NOT EXISTS admins
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password_hash TEXT)''')
    
    # Создаем администратора по умолчанию если нет
    c.execute("SELECT COUNT(*) FROM admins")
    if c.fetchone()[0] == 0:
        default_pass = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", 
                  ("admin", default_pass))
    
    conn.commit()
    conn.close()

init_db()

def generate_license_key(hardware_id=None):
    """Генерация уникального ключа лицензии"""
    if hardware_id:
        seed = hardware_id + str(uuid.uuid4())
    else:
        seed = str(uuid.uuid4())
    
    # Создаем читаемый ключ формата XXXX-XXXX-XXXX-XXXX
    hash_obj = hashlib.sha256(seed.encode()).hexdigest()
    key = '-'.join([hash_obj[i:i+4] for i in range(0, 16, 4)])
    return key.upper()

# HTML шаблон для страницы входа
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Вход в админ-панель</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            padding: 40px;
            width: 350px;
            text-align: center;
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
            text-align: left;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #555;
        }
        input {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            box-sizing: border-box;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
            transition: background 0.3s;
            width: 100%;
        }
        button:hover {
            background: #5a67d8;
        }
        .error-message {
            color: #dc3545;
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
            display: none;
        }
        .logo {
            font-size: 32px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">🛡️</div>
        <h1>Панель управления лицензиями</h1>
        
        <div id="error-message" class="error-message"></div>
        
        <form id="login-form" method="POST" action="/admin/login">
            <div class="form-group">
                <label>Логин:</label>
                <input type="text" name="username" placeholder="Введите логин" required>
            </div>
            <div class="form-group">
                <label>Пароль:</label>
                <input type="password" name="password" placeholder="Введите пароль" required>
            </div>
            <button type="submit">Войти</button>
        </form>
        
        <div style="margin-top: 20px; color: #666; font-size: 12px;">
            <p>Логин по умолчанию: <strong>admin</strong></p>
            <p>Пароль по умолчанию: <strong>admin123</strong></p>
            <p style="color: #dc3545; margin-top: 10px;">⚠️ Смените пароль после первого входа!</p>
        </div>
    </div>
    
    <script>
        document.getElementById('login-form').addEventListener('submit', function(e) {
            // Старая форма отправляется напрямую, без AJAX
            // Это более надежный способ
        });
    </script>
</body>
</html>
'''

# HTML шаблон для админ-панели
ADMIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Админ-панель лицензий</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .header {
            background: white;
            padding: 15px 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            margin: 0;
            color: #333;
            font-size: 24px;
        }
        .logout-btn {
            background: #dc3545;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
        }
        .logout-btn:hover {
            background: #c82333;
        }
        .container {
            max-width: 1200px;
            margin: 20px auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            padding: 30px;
        }
        .tab-buttons {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 1px solid #ddd;
        }
        .tab-button {
            padding: 10px 20px;
            background: #f5f5f5;
            border: none;
            border-radius: 5px 5px 0 0;
            margin-right: 5px;
            cursor: pointer;
            font-weight: bold;
        }
        .tab-button.active {
            background: #667eea;
            color: white;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #555;
        }
        input, select, textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
            transition: background 0.3s;
        }
        button:hover {
            background: #5a67d8;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f8f9fa;
            font-weight: bold;
            color: #495057;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .status-active {
            color: #28a745;
            font-weight: bold;
        }
        .status-inactive {
            color: #dc3545;
            font-weight: bold;
        }
        .search-box {
            margin-bottom: 20px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-number {
            font-size: 32px;
            font-weight: bold;
            margin: 10px 0;
        }
        .stat-label {
            font-size: 14px;
            opacity: 0.9;
        }
        .message {
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
            display: none;
        }
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .btn-danger {
            background: #dc3545;
        }
        .btn-danger:hover {
            background: #c82333;
        }
        .btn-success {
            background: #28a745;
        }
        .btn-success:hover {
            background: #218838;
        }
        .license-form {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ Панель управления лицензиями</h1>
        <button class="logout-btn" onclick="logout()">Выйти</button>
    </div>
    
    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Всего лицензий</div>
                <div class="stat-number" id="total-licenses">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Активных</div>
                <div class="stat-number" id="active-licenses">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Неактивных</div>
                <div class="stat-number" id="inactive-licenses">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Истекает скоро</div>
                <div class="stat-number" id="expiring-licenses">0</div>
            </div>
        </div>
        
        <div class="tab-buttons">
            <button class="tab-button active" onclick="showTab('manage')">Управление лицензиями</button>
            <button class="tab-button" onclick="showTab('create')">Создать лицензию</button>
            <button class="tab-button" onclick="showTab('search')">Поиск</button>
            <button class="tab-button" onclick="showTab('settings')">Настройки</button>
        </div>
        
        <div id="message" class="message"></div>
        
        <!-- Управление лицензиями -->
        <div id="manage" class="tab-content active">
            <div class="search-box">
                <input type="text" id="search-input" placeholder="Поиск по ключу, ID железа, имени..." 
                       onkeyup="searchLicenses()">
            </div>
            <div id="licenses-table">
                <!-- Таблица загрузится через JS -->
                <p>Загрузка данных...</p>
            </div>
        </div>
        
        <!-- Создание лицензии -->
        <div id="create" class="tab-content">
            <div class="license-form">
                <div>
                    <div class="form-group">
                        <label>Имя клиента:</label>
                        <input type="text" id="client-name" placeholder="Введите имя">
                    </div>
                    <div class="form-group">
                        <label>Email:</label>
                        <input type="email" id="client-email" placeholder="email@example.com">
                    </div>
                    <div class="form-group">
                        <label>Телефон:</label>
                        <input type="text" id="client-phone" placeholder="+7 XXX XXX XX XX">
                    </div>
                </div>
                <div>
                    <div class="form-group">
                        <label>ID железа (HWID):</label>
                        <input type="text" id="hardware-id" placeholder="Оставьте пустым для автоматической генерации">
                        <small>Если пусто - будет создана лицензия без привязки к железу</small>
                    </div>
                    <div class="form-group">
                        <label>Срок действия (дней):</label>
                        <select id="expiry-days">
                            <option value="30">30 дней</option>
                            <option value="90">90 дней</option>
                            <option value="180">180 дней</option>
                            <option value="365">1 год</option>
                            <option value="730">2 года</option>
                            <option value="0">Бессрочная</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Примечания:</label>
                        <textarea id="notes" rows="3" placeholder="Дополнительная информация"></textarea>
                    </div>
                </div>
            </div>
            <button onclick="createLicense()">Создать лицензию</button>
        </div>
        
        <!-- Поиск -->
        <div id="search" class="tab-content">
            <div class="form-group">
                <label>Тип поиска:</label>
                <select id="search-type">
                    <option value="all">Все лицензии</option>
                    <option value="key">По ключу лицензии</option>
                    <option value="hwid">По ID железа</option>
                    <option value="name">По имени клиента</option>
                    <option value="email">По email</option>
                    <option value="active">Только активные</option>
                    <option value="inactive">Только неактивные</option>
                    <option value="expiring">Истекающие в течение 30 дней</option>
                </select>
            </div>
            <div class="form-group" id="search-query-group" style="display: none;">
                <label>Поисковый запрос:</label>
                <input type="text" id="search-query" placeholder="Введите запрос...">
            </div>
            <button onclick="performSearch()">Выполнить поиск</button>
            <div id="search-results" style="margin-top: 20px;"></div>
        </div>
        
        <!-- Настройки -->
        <div id="settings" class="tab-content">
            <div class="form-group">
                <label>Сменить пароль администратора:</label>
                <input type="password" id="new-password" placeholder="Новый пароль">
                <input type="password" id="confirm-password" placeholder="Подтвердите пароль" 
                       style="margin-top: 10px;">
            </div>
            <button onclick="changePassword()">Сменить пароль</button>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                <h3>Информация о сервере</h3>
                <p><strong>Версия:</strong> 1.0.0</p>
                <p><strong>Автор:</strong> @mtashnik55</p>
                <p><strong>База данных:</strong> licenses.db</p>
                <p><strong>API эндпоинты:</strong></p>
                <ul>
                    <li>POST /api/check - Проверка лицензии</li>
                    <li>POST /api/activate - Активация лицензии</li>
                    <li>GET /api/licenses - Получить все лицензии (требует auth)</li>
                    <li>POST /api/create - Создать лицензию (требует auth)</li>
                </ul>
            </div>
        </div>
    </div>
    
    <script>
        let currentTab = 'manage';
        
        // Функция для получения заголовков авторизации
        function getAuthHeader() {
            // Используем Basic Auth через браузерный prompt
            const username = localStorage.getItem('admin_username') || 'admin';
            const password = localStorage.getItem('admin_password') || '';
            
            if (!password) {
                // Если пароль не сохранен, запрашиваем у пользователя
                const auth = prompt('Введите логин и пароль (формат: логин:пароль):', 'admin:admin123');
                if (auth) {
                    const [user, pass] = auth.split(':');
                    localStorage.setItem('admin_username', user);
                    localStorage.setItem('admin_password', pass);
                    return {
                        'Authorization': 'Basic ' + btoa(auth)
                    };
                }
                return {};
            }
            
            return {
                'Authorization': 'Basic ' + btoa(username + ':' + password)
            };
        }
        
        // Функция для отправки запросов с обработкой 401 ошибки
        async function fetchWithAuth(url, options = {}) {
            const headers = {
                ...getAuthHeader(),
                ...options.headers,
                'Content-Type': 'application/json'
            };
            
            const response = await fetch(url, { ...options, headers });
            
            if (response.status === 401) {
                // Очищаем сохраненные данные
                localStorage.removeItem('admin_username');
                localStorage.removeItem('admin_password');
                // Показываем ошибку
                showMessage('Требуется авторизация. Обновите страницу.', 'error');
                return null;
            }
            
            return response;
        }
        
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
            currentTab = tabName;
            
            if (tabName === 'manage') {
                loadLicenses();
                updateStats();
            }
        }
        
        function showMessage(text, type = 'success') {
            const msgDiv = document.getElementById('message');
            msgDiv.textContent = text;
            msgDiv.className = `message ${type}`;
            msgDiv.style.display = 'block';
            setTimeout(() => {
                msgDiv.style.display = 'none';
            }, 5000);
        }
        
        async function loadLicenses() {
            try {
                const response = await fetchWithAuth('/api/licenses');
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    renderLicensesTable(data.licenses);
                } else {
                    document.getElementById('licenses-table').innerHTML = 
                        '<p class="error">Ошибка загрузки данных: ' + (data.error || 'Неизвестная ошибка') + '</p>';
                }
            } catch (error) {
                console.error('Error loading licenses:', error);
                document.getElementById('licenses-table').innerHTML = 
                    '<p class="error">Ошибка загрузки данных: ' + error.message + '</p>';
            }
        }
        
        function renderLicensesTable(licenses) {
            if (licenses.length === 0) {
                document.getElementById('licenses-table').innerHTML = 
                    '<p>Нет лицензий в базе данных</p>';
                return;
            }
            
            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>Ключ лицензии</th>
                            <th>ID железа</th>
                            <th>Клиент</th>
                            <th>Дата создания</th>
                            <th>Срок действия</th>
                            <th>Статус</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            licenses.forEach(license => {
                const expiryDate = license.expiry_date ? 
                    new Date(license.expiry_date).toLocaleDateString('ru-RU') : 'Бессрочная';
                const status = license.is_active ? 
                    '<span class="status-active">Активна</span>' : 
                    '<span class="status-inactive">Неактивна</span>';
                
                html += `
                    <tr>
                        <td><code>${license.license_key}</code></td>
                        <td>${license.hardware_id || 'Не привязано'}</td>
                        <td>
                            <strong>${license.client_name || 'Не указано'}</strong><br>
                            ${license.email || ''}<br>
                            ${license.phone || ''}
                        </td>
                        <td>${new Date(license.created_date).toLocaleDateString('ru-RU')}</td>
                        <td>${expiryDate}</td>
                        <td>${status}</td>
                        <td>
                            <button onclick="toggleLicense(${license.id}, ${license.is_active})" 
                                    class="${license.is_active ? 'btn-danger' : 'btn-success'}">
                                ${license.is_active ? 'Деактивировать' : 'Активировать'}
                            </button>
                            <button onclick="deleteLicense(${license.id})" 
                                    style="background: #6c757d; margin-left: 5px;">
                                Удалить
                            </button>
                        </td>
                    </tr>
                `;
            });
            
            html += '</tbody></table>';
            document.getElementById('licenses-table').innerHTML = html;
        }
        
        async function updateStats() {
            try {
                const response = await fetchWithAuth('/api/stats');
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('total-licenses').textContent = data.total;
                    document.getElementById('active-licenses').textContent = data.active;
                    document.getElementById('inactive-licenses').textContent = data.inactive;
                    document.getElementById('expiring-licenses').textContent = data.expiring_soon;
                }
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }
        
        async function createLicense() {
            const licenseData = {
                client_name: document.getElementById('client-name').value,
                email: document.getElementById('client-email').value,
                phone: document.getElementById('client-phone').value,
                hardware_id: document.getElementById('hardware-id').value || null,
                expiry_days: parseInt(document.getElementById('expiry-days').value),
                notes: document.getElementById('notes').value
            };
            
            try {
                const response = await fetchWithAuth('/api/create', {
                    method: 'POST',
                    body: JSON.stringify(licenseData)
                });
                
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage(`Лицензия создана! Ключ: ${data.license_key}`, 'success');
                    // Очистить форму
                    ['client-name', 'client-email', 'client-phone', 'hardware-id', 'notes'].forEach(id => {
                        document.getElementById(id).value = '';
                    });
                    
                    // Перезагрузить таблицу
                    loadLicenses();
                    updateStats();
                } else {
                    showMessage(`Ошибка: ${data.error}`, 'error');
                }
            } catch (error) {
                showMessage('Ошибка соединения с сервером', 'error');
            }
        }
        
        async function toggleLicense(licenseId, isActive) {
            if (!confirm(`Вы уверены, что хотите ${isActive ? 'деактивировать' : 'активировать'} эту лицензию?`)) {
                return;
            }
            
            try {
                const response = await fetchWithAuth(`/api/toggle/${licenseId}`, {
                    method: 'POST'
                });
                
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage(`Лицензия ${isActive ? 'деактивирована' : 'активирована'}!`, 'success');
                    loadLicenses();
                    updateStats();
                } else {
                    showMessage(`Ошибка: ${data.error}`, 'error');
                }
            } catch (error) {
                showMessage('Ошибка соединения с сервером', 'error');
            }
        }
        
        async function deleteLicense(licenseId) {
            if (!confirm('Вы уверены, что хотите удалить эту лицензию? Это действие нельзя отменить.')) {
                return;
            }
            
            try {
                const response = await fetchWithAuth(`/api/delete/${licenseId}`, {
                    method: 'DELETE'
                });
                
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage('Лицензия удалена!', 'success');
                    loadLicenses();
                    updateStats();
                } else {
                    showMessage(`Ошибка: ${data.error}`, 'error');
                }
            } catch (error) {
                showMessage('Ошибка соединения с сервером', 'error');
            }
        }
        
        document.getElementById('search-type').addEventListener('change', function() {
            const queryGroup = document.getElementById('search-query-group');
            queryGroup.style.display = ['all', 'active', 'inactive', 'expiring'].includes(this.value) ? 
                'none' : 'block';
        });
        
        async function performSearch() {
            const searchType = document.getElementById('search-type').value;
            const searchQuery = document.getElementById('search-query').value;
            
            let url = '/api/search?type=' + encodeURIComponent(searchType);
            if (searchQuery) {
                url += '&query=' + encodeURIComponent(searchQuery);
            }
            
            try {
                const response = await fetchWithAuth(url);
                if (!response) return;
                
                const data = await response.json();
                
                const resultsDiv = document.getElementById('search-results');
                
                if (data.success && data.licenses.length > 0) {
                    renderSearchResults(data.licenses, resultsDiv);
                } else {
                    resultsDiv.innerHTML = '<p>Ничего не найдено</p>';
                }
            } catch (error) {
                console.error('Error searching:', error);
            }
        }
        
        function renderSearchResults(licenses, container) {
            let html = '<h3>Результаты поиска:</h3>';
            html += '<table><thead><tr><th>Ключ</th><th>Клиент</th><th>ID железа</th><th>Статус</th></tr></thead><tbody>';
            
            licenses.forEach(license => {
                const status = license.is_active ? 
                    '<span class="status-active">Активна</span>' : 
                    '<span class="status-inactive">Неактивна</span>';
                
                html += `
                    <tr>
                        <td><code>${license.license_key}</code></td>
                        <td>${license.client_name || 'Не указано'}</td>
                        <td>${license.hardware_id || 'Не привязано'}</td>
                        <td>${status}</td>
                    </tr>
                `;
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
        
        async function changePassword() {
            const newPass = document.getElementById('new-password').value;
            const confirmPass = document.getElementById('confirm-password').value;
            
            if (!newPass) {
                showMessage('Введите новый пароль', 'error');
                return;
            }
            
            if (newPass !== confirmPass) {
                showMessage('Пароли не совпадают', 'error');
                return;
            }
            
            if (!confirm('Вы уверены, что хотите сменить пароль?')) {
                return;
            }
            
            try {
                const response = await fetchWithAuth('/api/change_password', {
                    method: 'POST',
                    body: JSON.stringify({password: newPass})
                });
                
                if (!response) return;
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage('Пароль успешно изменен!', 'success');
                    document.getElementById('new-password').value = '';
                    document.getElementById('confirm-password').value = '';
                } else {
                    showMessage(`Ошибка: ${data.error}`, 'error');
                }
            } catch (error) {
                showMessage('Ошибка соединения', 'error');
            }
        }
        
        function searchLicenses() {
            const query = document.getElementById('search-input').value.toLowerCase();
            const rows = document.querySelectorAll('#licenses-table table tbody tr');
            
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            });
        }
        
        function logout() {
            localStorage.removeItem('admin_username');
            localStorage.removeItem('admin_password');
            window.location.href = '/login';
        }
        
        // При загрузке страницы проверяем, есть ли сохраненные данные
        document.addEventListener('DOMContentLoaded', function() {
            // Запрашиваем данные при загрузке
            loadLicenses();
            updateStats();
        });
    </script>
</body>
</html>
'''

# Простой декоратор для проверки аутентификации
def require_auth(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_admin_auth(auth.username, auth.password):
            # Возвращаем 401 ошибку
            return jsonify({'success': False, 'error': 'Требуется аутентификация'}), 401
        return f(*args, **kwargs)
    return decorated_function

def check_admin_auth(username, password):
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admins WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return result[0] == hashlib.sha256(password.encode()).hexdigest()
    return False

# Роуты для админ-панели
@app.route('/')
def index():
    """Перенаправляем на страницу входа"""
    return redirect('/login')

@app.route('/login')
def login_page():
    """Страница входа"""
    return LOGIN_TEMPLATE

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Обработка входа в админ-панель"""
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        return "Не указаны логин или пароль", 400
    
    if check_admin_auth(username, password):
        # Создаем ответ с админ-панелью
        response = make_response(ADMIN_TEMPLATE)
        
        # Устанавливаем заголовок авторизации для браузера
        auth_string = f"{username}:{password}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        
        # Добавляем JavaScript для сохранения данных
        script = f'''
        <script>
            localStorage.setItem('admin_username', '{username}');
            localStorage.setItem('admin_password', '{password}');
        </script>
        '''
        
        # Добавляем скрипт в ответ
        response.data = response.data.decode().replace('</body>', script + '</body>')
        return response
    else:
        return "Неверный логин или пароль", 401

@app.route('/admin')
def admin_panel():
    """Админ-панель (прямой доступ)"""
    # Проверяем авторизацию через заголовки
    auth = request.authorization
    if not auth or not check_admin_auth(auth.username, auth.password):
        # Возвращаем 401, чтобы браузер показал диалог авторизации
        return make_response(
            'Требуется авторизация',
            401,
            {'WWW-Authenticate': 'Basic realm="Admin Panel"'}
        )
    return ADMIN_TEMPLATE

# API Endpoints для программы (не требуют аутентификации админа)
@app.route('/api/check', methods=['POST'])
def check_license():
    """Проверка лицензии клиентом"""
    data = request.json
    license_key = data.get('license_key')
    hardware_id = data.get('hardware_id')
    
    if not license_key or not hardware_id:
        return jsonify({'success': False, 'error': 'Отсутствуют обязательные параметры'})
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Ищем лицензию
    c.execute('''SELECT * FROM licenses 
                 WHERE license_key = ? AND is_active = 1''', (license_key,))
    license_data = c.fetchone()
    
    if not license_data:
        conn.close()
        return jsonify({'success': False, 'error': 'Лицензия не найдена или неактивна'})
    
    # Проверяем привязку к железу
    license_hwid = license_data[2]  # hardware_id из БД
    if license_hwid and license_hwid != hardware_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Лицензия привязана к другому компьютеру'})
    
    # Проверяем срок действия (ИСПРАВЛЕНО)
    expiry_date = license_data[6]  # expiry_date из БД
    
    if expiry_date:
        try:
            # Парсим дату, убираем микросекунды если есть
            if '.' in expiry_date:
                expiry_date = expiry_date.split('.')[0]
            
            # Парсим дату
            expiry_datetime = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
            
            # Добавляем время до конца дня
            expiry_datetime = expiry_datetime.replace(hour=23, minute=59, second=59)
            
            if datetime.now() > expiry_datetime:
                conn.close()
                return jsonify({'success': False, 'error': 'Срок действия лицензии истек'})
        except Exception as e:
            print(f"Ошибка парсинга даты: {e}, expiry_date: {expiry_date}")
            # Если ошибка парсинга, считаем лицензию валидной
    
    # Если лицензия не привязана к железу - привязываем ее
    if not license_hwid:
        c.execute('''UPDATE licenses 
                     SET hardware_id = ? 
                     WHERE license_key = ?''', (hardware_id, license_key))
        conn.commit()
    
    conn.close()
    return jsonify({
        'success': True,
        'license_key': license_key,
        'client_name': license_data[3],
        'expiry_date': expiry_date,
        'is_unlimited': not bool(expiry_date)
    })

@app.route('/api/activate', methods=['POST'])
def activate_license():
    """Активация лицензии (для программы)"""
    data = request.json
    hardware_id = data.get('hardware_id')
    
    if not hardware_id:
        return jsonify({'success': False, 'error': 'Не указан ID железа'})
    
    # Генерируем ключ лицензии
    license_key = generate_license_key(hardware_id)
    
    # Создаем лицензию в БД
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Создаем бессрочную лицензию для этого железа
    try:
        c.execute('''INSERT INTO licenses 
                     (license_key, hardware_id, created_date, is_active) 
                     VALUES (?, ?, ?, ?)''',
                  (license_key, hardware_id, datetime.now().isoformat(), 1))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'license_key': license_key,
            'message': 'Лицензия создана и активирована'
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            'success': False, 
            'error': 'Для этого компьютера уже есть лицензия'
        })

# Защищенные API endpoints (требуют аутентификации админа)
@app.route('/api/licenses', methods=['GET'])
@require_auth
def get_licenses_endpoint():
    """Получить все лицензии (только для админа)"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute('''SELECT * FROM licenses ORDER BY created_date DESC''')
    columns = [description[0] for description in c.description]
    licenses = []
    
    for row in c.fetchall():
        license_dict = {}
        for i, col in enumerate(columns):
            license_dict[col] = row[i]
        licenses.append(license_dict)
    
    conn.close()
    return jsonify({'success': True, 'licenses': licenses})

@app.route('/api/create', methods=['POST'])
@require_auth
def create_license_admin():
    """Создать лицензию (админ)"""
    data = request.json
    
    client_name = data.get('client_name', '')
    email = data.get('email', '')
    phone = data.get('phone', '')
    hardware_id = data.get('hardware_id')
    expiry_days = data.get('expiry_days', 0)
    notes = data.get('notes', '')
    
    # Генерируем ключ
    license_key = generate_license_key(hardware_id)
    
    # Рассчитываем дату окончания
    created_date = datetime.now()
    expiry_date = None
    
    # Исправляем логику срока действия
    if expiry_days and int(expiry_days) > 0:
        expiry_date = (created_date + timedelta(days=int(expiry_days))).isoformat()
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    try:
        c.execute('''INSERT INTO licenses 
                     (license_key, hardware_id, client_name, email, phone, 
                      created_date, expiry_date, is_active, notes) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (license_key, hardware_id, client_name, email, phone,
                   created_date.isoformat(), expiry_date, 1, notes))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'license_key': license_key,
            'message': 'Лицензия создана успешно'
        })
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({
            'success': False, 
            'error': 'Лицензия с таким ключом или HWID уже существует'
        })

@app.route('/api/toggle/<int:license_id>', methods=['POST'])
@require_auth
def toggle_license_endpoint(license_id):
    """Активировать/деактивировать лицензию"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Получаем текущий статус
    c.execute('SELECT is_active FROM licenses WHERE id = ?', (license_id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        return jsonify({'success': False, 'error': 'Лицензия не найдена'})
    
    new_status = 0 if result[0] else 1
    
    c.execute('''UPDATE licenses 
                 SET is_active = ? 
                 WHERE id = ?''', (new_status, license_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'new_status': new_status})

@app.route('/api/delete/<int:license_id>', methods=['DELETE'])
@require_auth
def delete_license_endpoint(license_id):
    """Удалить лицензию"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute('DELETE FROM licenses WHERE id = ?', (license_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats_endpoint():
    """Статистика по лицензиям"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Общее количество
    c.execute('SELECT COUNT(*) FROM licenses')
    total = c.fetchone()[0]
    
    # Активные
    c.execute('SELECT COUNT(*) FROM licenses WHERE is_active = 1')
    active = c.fetchone()[0]
    
    # Неактивные
    inactive = total - active
    
    # Истекающие скоро (в течение 30 дней)
    thirty_days_later = (datetime.now() + timedelta(days=30)).isoformat()
    c.execute('''SELECT COUNT(*) FROM licenses 
                 WHERE expiry_date IS NOT NULL 
                 AND expiry_date <= ? 
                 AND is_active = 1''', (thirty_days_later,))
    expiring_soon = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'success': True,
        'total': total,
        'active': active,
        'inactive': inactive,
        'expiring_soon': expiring_soon
    })

@app.route('/api/search', methods=['GET'])
@require_auth
def search_licenses_endpoint():
    """Поиск лицензий"""
    search_type = request.args.get('type', 'all')
    query = request.args.get('query', '')
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    sql = 'SELECT * FROM licenses WHERE 1=1'
    params = []
    
    if search_type == 'key' and query:
        sql += ' AND license_key LIKE ?'
        params.append(f'%{query}%')
    elif search_type == 'hwid' and query:
        sql += ' AND hardware_id LIKE ?'
        params.append(f'%{query}%')
    elif search_type == 'name' and query:
        sql += ' AND client_name LIKE ?'
        params.append(f'%{query}%')
    elif search_type == 'email' and query:
        sql += ' AND email LIKE ?'
        params.append(f'%{query}%')
    elif search_type == 'active':
        sql += ' AND is_active = 1'
    elif search_type == 'inactive':
        sql += ' AND is_active = 0'
    elif search_type == 'expiring':
        thirty_days_later = (datetime.now() + timedelta(days=30)).isoformat()
        sql += ' AND expiry_date IS NOT NULL AND expiry_date <= ? AND is_active = 1'
        params.append(thirty_days_later)
    
    sql += ' ORDER BY created_date DESC'
    
    c.execute(sql, params)
    columns = [description[0] for description in c.description]
    licenses = []
    
    for row in c.fetchall():
        license_dict = {}
        for i, col in enumerate(columns):
            license_dict[col] = row[i]
        licenses.append(license_dict)
    
    conn.close()
    return jsonify({'success': True, 'licenses': licenses})

@app.route('/api/change_password', methods=['POST'])
@require_auth
def change_password_endpoint():
    """Сменить пароль администратора"""
    data = request.json
    new_password = data.get('password')
    
    if not new_password or len(new_password) < 6:
        return jsonify({'success': False, 'error': 'Пароль должен быть не менее 6 символов'})
    
    password_hash = hashlib.sha256(new_password.encode()).hexdigest()
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Получаем текущее имя пользователя из аутентификации
    auth = request.authorization
    c.execute('''UPDATE admins 
                 SET password_hash = ? 
                 WHERE username = ?''', (password_hash, auth.username))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Пароль успешно изменен'})

if __name__ == '__main__':
    print("=" * 50)
    print("Сервер лицензий MTA Light Generator")
    print("Автор: @mtashnik55")
    print("=" * 50)
    print("\n📊 Админ-панель доступна по адресу: http://localhost:5000")
    print("👤 Логин: admin")
    print("🔑 Пароль: admin123")
    print("\n⚠️  Смените пароль сразу после первого входа!")
    print("=" * 50)
    
    # Запускаем сервер
    app.run(host='0.0.0.0', port=5000, debug=True)