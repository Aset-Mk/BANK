from flask import Flask, render_template, request, redirect, url_for, session, flash
from db import Database

app = Flask(__name__)
app.secret_key = 'super_secret_key_bank_moneta' # Для работы сессий
db = Database()

# Настройка комиссии банка (15%)
LOAN_RATE = 0.15 

# --- Декораторы и утилиты ---
def login_required(role=None):
    # Простая проверка авторизации внутри роутов
    if 'user' not in session:
        return redirect(url_for('login'))
    if role and session.get('role') != role:
        return "Доступ запрещен", 403
    return None

@app.route('/')
def index():
    if 'user' in session:
        role = session['role']
        if role == 'client': return redirect(url_for('client_dash'))
        if role == 'manager': return redirect(url_for('manager_dash'))
        if role == 'admin': return redirect(url_for('admin_dash'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = db.get_user(username, password)
        
        if user:
            # Проверка блокировки
            if user['is_blocked']:
                session['blocked_user'] = username # Запоминаем для апелляции
                return redirect(url_for('blocked'))
            
            session['user'] = user['username']
            session['role'] = user['role']
            session['name'] = user['name']
            return redirect(url_for('index'))
        else:
            flash('Неверный логин или пароль', 'danger')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if db.create_user(request.form['username'], request.form['password'], 'client', 
                          request.form['name'], request.form['email']):
            flash('Регистрация успешна! Войдите.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Логин уже занят', 'danger')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/blocked', methods=['GET', 'POST'])
def blocked():
    username = session.get('blocked_user')
    if not username: return redirect(url_for('login'))
    
    if request.method == 'POST':
        message = request.form['message']
        db.create_appeal(username, message)
        flash('Апелляция отправлена администратору.', 'info')
        session.pop('blocked_user', None)
        return redirect(url_for('login'))
        
    return render_template('blocked.html', username=username)

# --- CLIENT Routes ---
@app.route('/dashboard')
def client_dash():
    check = login_required('client')
    if check: return check
    
    accounts = db.get_client_accounts(session['user'])
    history = db.get_history(session['user'])
    loans = db.get_client_loans(session['user']) 
    
    # Передаем loan_rate в шаблон, чтобы клиент видел процентную ставку
    return render_template('client.html', 
                           accounts=accounts, 
                           history=history, 
                           loans=loans, 
                           user=session['name'],
                           loan_rate=int(LOAN_RATE * 100)) # Передаем как целое число (15)

@app.route('/transaction', methods=['POST'])
def transaction():
    action = request.form['action']
    acc_num = request.form['account_number']
    
    if action == 'deposit':
        amount = float(request.form['amount'])
        db.deposit(acc_num, amount)
        flash('Баланс пополнен', 'success')
        
    elif action == 'transfer':
        to_acc = request.form['to_account']
        amount = float(request.form['amount'])
        res = db.transfer(acc_num, to_acc, amount)
        flash(res, 'success' if res == 'Успешно' else 'danger')
        
    return redirect(url_for('client_dash'))

@app.route('/loan_request', methods=['POST'])
def loan_request():
    try:
        amount = float(request.form['amount'])
        term = int(request.form['term'])
    except ValueError:
        flash('Некорректные данные', 'danger')
        return redirect(url_for('client_dash'))
    
    # Расчет полной суммы возврата для уведомления пользователя
    total_repayment = amount * (1 + LOAN_RATE)
    
    # В БД передаем базовые данные, математику начисления сделаем внутри метода request_loan
    db.request_loan(session['user'], amount, term)
    
    flash(f'Заявка на {amount:,.0f} ₸ отправлена. С учетом комиссии ({int(LOAN_RATE*100)}%) к возврату: {total_repayment:,.0f} ₸', 'info')
    return redirect(url_for('client_dash'))

@app.route('/repay_loan', methods=['POST'])
def repay_loan():
    check = login_required('client')
    if check: return check

    loan_id = request.form.get('loan_id')
    account_number = request.form.get('account_number')
    try:
        amount = float(request.form.get('amount'))
    except (ValueError, TypeError):
        flash('Некорректная сумма', 'danger')
        return redirect(url_for('client_dash'))

    result = db.repay_loan(loan_id, account_number, amount)

    if result['success']:
        flash('Платеж по кредиту успешно выполнен!', 'success')
    else:
        flash(f"Ошибка: {result['message']}", 'danger')

    return redirect(url_for('client_dash'))

@app.route('/create_account')
def create_account():
    db.create_account(session['user'], 'Текущий')
    return redirect(url_for('client_dash'))

# --- MANAGER Routes ---
@app.route('/manager')
def manager_dash():
    check = login_required('manager')
    if check: return check
    loans = db.get_loans('pending')
    return render_template('manager.html', loans=loans)

@app.route('/process_loan/<int:loan_id>/<decision>')
def process_loan(loan_id, decision):
    db.process_loan(loan_id, decision)
    return redirect(url_for('manager_dash'))

# --- ADMIN Routes ---
@app.route('/admin')
def admin_dash():
    check = login_required('admin')
    if check: return check
    users = db.get_all_users()
    appeals = db.get_open_appeals()
    return render_template('admin.html', users=users, appeals=appeals)

@app.route('/toggle_block/<username>/<int:status>')
def toggle_block(username, status):
    user = db.get_user_by_name(username)
    if user['role'] == 'admin':
        flash('Нельзя блокировать админа', 'danger')
    else:
        db.set_block_status(username, status)
    return redirect(url_for('admin_dash'))

@app.route('/resolve_appeal/<int:appeal_id>/<username>')
def resolve_appeal(appeal_id, username):
    db.resolve_appeal(appeal_id, username)
    flash(f'Пользователь {username} разблокирован', 'success')
    return redirect(url_for('admin_dash'))

if __name__ == '__main__':
    app.run(debug=True)
