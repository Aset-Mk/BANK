import sqlite3
import hashlib
import random
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_name="bank_system.db"):
        self.db_name = db_name
        self.create_tables()
        self.seed_data()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к полям по имени (row['field'])
        return conn

    def hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    # --- Генерация данных карты ---
    def generate_card_details(self):
        # 1. Генерация номера (начинается с 4 или 5)
        prefix = random.choice(['4', '5'])
        remaining = ''.join([str(random.randint(0, 9)) for _ in range(15)])
        card_number = prefix + remaining
        
        # 2. CVV (3 цифры)
        cvv = str(random.randint(100, 999))
        
        # 3. Срок действия (+3 года)
        future_date = datetime.now() + timedelta(days=365*3)
        expiry_date = future_date.strftime("%m/%y")
        
        return card_number, cvv, expiry_date

    def create_tables(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL,
                name TEXT, email TEXT, created_at TEXT, is_blocked INTEGER DEFAULT 0)''')
            
            # Таблица счетов (с данными карты)
            cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (
                account_number TEXT PRIMARY KEY, 
                username TEXT, 
                type TEXT,
                balance REAL DEFAULT 0.0, 
                card_number TEXT,
                cvv TEXT,
                expiry_date TEXT,
                FOREIGN KEY(username) REFERENCES users(username))''')
            
            # Таблица транзакций
            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account_number TEXT, type TEXT,
                amount REAL, description TEXT, timestamp TEXT,
                FOREIGN KEY(account_number) REFERENCES accounts(account_number))''')
            
            # Таблица кредитов
            cursor.execute('''CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, amount REAL,
                term_months INTEGER, status TEXT DEFAULT 'pending', created_at TEXT,
                remaining_amount REAL,
                FOREIGN KEY(username) REFERENCES users(username))''')
            
            # МИГРАЦИЯ: Проверяем, есть ли поле remaining_amount
            cursor.execute("PRAGMA table_info(loans)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'remaining_amount' not in columns:
                cursor.execute("ALTER TABLE loans ADD COLUMN remaining_amount REAL")
            
            # Таблица обращений
            cursor.execute('''CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT,
                status TEXT DEFAULT 'open', created_at TEXT,
                FOREIGN KEY(username) REFERENCES users(username))''')
            conn.commit()

    def seed_data(self):
        users = [
            ('admin', 'Adm!n47', 'admin', 'Админ', 'admin1@bank.kz'),
            ('manager', 'Manag3r45', 'manager', 'Менеджер Иван', 'manager@bank.kz'),
            ('client', 'Cl!ent42', 'client', 'Тестовый Клиент', 'client@bank.kz')
        ]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for u in users:
                if not cursor.execute("SELECT * FROM users WHERE username=?", (u[0],)).fetchone():
                    hashed_pw = self.hash_password(u[1])
                    cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, 0)", 
                                   (u[0], hashed_pw, u[2], u[3], u[4], datetime.now()))
                    if u[2] == 'client':
                        self.create_account(u[0], 'Checking', conn)

    # --- Пользователи (Users) ---
    def get_user(self, username, password):
        hashed_pw = self.hash_password(password)
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed_pw)).fetchone()

    def get_user_by_name(self, username):
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def create_user(self, username, password, role, name, email):
        try:
            hashed_pw = self.hash_password(password)
            with self.get_connection() as conn:
                conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, 0)",
                             (username, hashed_pw, role, name, email, datetime.now()))
                if role == 'client':
                    self.create_account(username, 'Текущий', conn)
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_all_users(self):
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM users").fetchall()

    def set_block_status(self, username, status):
        with self.get_connection() as conn:
            conn.execute("UPDATE users SET is_blocked=? WHERE username=?", (status, username))
            conn.commit()

    # --- Счета (Accounts) ---
    def create_account(self, username, acc_type, existing_conn=None):
        conn = existing_conn if existing_conn else self.get_connection()
        try:
            cursor = conn.cursor()
            res = cursor.execute("SELECT COUNT(*) FROM accounts").fetchone()
            acc_num = f"KZ{2000 + res[0] + 1}"
            card_num, cvv, exp_date = self.generate_card_details()

            cursor.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (acc_num, username, acc_type, 0.0, card_num, cvv, exp_date))
            
            if not existing_conn: conn.commit()
            return acc_num
        finally:
            if not existing_conn: conn.close()

    def get_client_accounts(self, username):
        with self.get_connection() as conn:
            return conn.execute('''
                SELECT a.*, u.name as owner_name 
                FROM accounts a 
                JOIN users u ON a.username = u.username 
                WHERE a.username=?
            ''', (username,)).fetchall()

    def transfer(self, from_acc, to_acc, amount):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            sender = cursor.execute("SELECT balance FROM accounts WHERE account_number=?", (from_acc,)).fetchone()
            target = cursor.execute("SELECT * FROM accounts WHERE account_number=?", (to_acc,)).fetchone()
            
            if not sender: return "Счет отправителя не найден"
            if not target: return "Счет получателя не найден"
            if sender['balance'] < amount: return "Недостаточно средств"

            cursor.execute("UPDATE accounts SET balance = balance - ? WHERE account_number=?", (amount, from_acc))
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE account_number=?", (amount, to_acc))
            
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO transactions (account_number, type, amount, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                           (from_acc, "TRANSFER_OUT", amount, f"Перевод на {to_acc}", ts))
            cursor.execute("INSERT INTO transactions (account_number, type, amount, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                           (to_acc, "TRANSFER_IN", amount, f"Перевод от {from_acc}", ts))
            conn.commit()
            return "Успешно"

    def deposit(self, acc_num, amount):
        with self.get_connection() as conn:
            conn.execute("UPDATE accounts SET balance = balance + ? WHERE account_number=?", (amount, acc_num))
            conn.execute("INSERT INTO transactions (account_number, type, amount, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                           (acc_num, "DEPOSIT", amount, "Пополнение", datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()

    def get_history(self, username):
        with self.get_connection() as conn:
            query = '''SELECT t.* FROM transactions t JOIN accounts a ON t.account_number = a.account_number 
                       WHERE a.username = ? ORDER BY t.timestamp DESC'''
            return conn.execute(query, (username,)).fetchall()

    # --- Кредиты (Loans) ---
    def request_loan(self, username, amount, months):
        """Создание заявки на кредит с начислением процентов (15%)"""
        with self.get_connection() as conn:
            # ИЗМЕНЕНИЕ ЗДЕСЬ:
            # amount - сумма, которую клиент хочет получить (и получит при одобрении).
            # total_debt - сумма, которую он должен банку (amount + 15%).
            interest_rate = 0.15
            total_debt = amount * (1 + interest_rate)
            
            conn.execute("INSERT INTO loans (username, amount, term_months, created_at, remaining_amount) VALUES (?, ?, ?, ?, ?)",
                         (username, amount, months, datetime.now().strftime("%Y-%m-%d"), total_debt))
            conn.commit()

    def get_loans(self, status):
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM loans WHERE status=?", (status,)).fetchall()

    def get_client_loans(self, username):
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM loans WHERE username=?", (username,)).fetchall()

    def process_loan(self, loan_id, decision):
        with self.get_connection() as conn:
            loan = conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
            if not loan: return False
            
            conn.execute("UPDATE loans SET status=? WHERE id=?", (decision, loan_id))

            if decision == 'approved':
                acc = conn.execute("SELECT account_number FROM accounts WHERE username=? LIMIT 1", (loan['username'],)).fetchone()
                if acc:
                    # Клиент получает "чистую" сумму (amount), но долг (remaining_amount) уже записан с процентами
                    conn.execute("UPDATE accounts SET balance = balance + ? WHERE account_number=?", (loan['amount'], acc['account_number']))
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                    conn.execute("INSERT INTO transactions (account_number, type, amount, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                                   (acc['account_number'], "LOAN_APPROVED", loan['amount'], "Кредитные средства", ts))
            
            conn.commit()
            return True

    def repay_loan(self, loan_id, account_number, amount):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            acc = cursor.execute("SELECT balance FROM accounts WHERE account_number=?", (account_number,)).fetchone()
            if not acc: return {'success': False, 'message': 'Счет не найден'}
            if acc['balance'] < amount: return {'success': False, 'message': 'Недостаточно средств на счете'}

            loan = cursor.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
            if not loan or loan['status'] != 'approved': return {'success': False, 'message': 'Кредит не активен'}

            current_debt = loan['remaining_amount'] if loan['remaining_amount'] is not None else loan['amount']
            
            if amount > current_debt + 1:
                return {'success': False, 'message': 'Сумма превышает остаток долга'}

            new_balance = acc['balance'] - amount
            new_debt = current_debt - amount
            if new_debt < 0: new_debt = 0

            new_status = 'paid' if new_debt <= 0 else 'approved'

            cursor.execute("UPDATE accounts SET balance = ? WHERE account_number = ?", (new_balance, account_number))
            cursor.execute("UPDATE loans SET remaining_amount = ?, status = ? WHERE id = ?", (new_debt, new_status, loan_id))

            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO transactions (account_number, type, amount, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                           (account_number, "LOAN_REPAYMENT", amount, f"Погашение кредита #{loan_id}", ts))
            
            conn.commit()
            return {'success': True}

    # --- Обращения (Appeals) ---
    def create_appeal(self, username, message):
        with self.get_connection() as conn:
            conn.execute("INSERT INTO appeals (username, message, created_at) VALUES (?, ?, ?)",
                         (username, message, datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()

    def get_open_appeals(self):
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM appeals WHERE status='open'").fetchall()

    def resolve_appeal(self, appeal_id, username):
        with self.get_connection() as conn:
            conn.execute("UPDATE appeals SET status='resolved' WHERE id=?", (appeal_id,))
            conn.execute("UPDATE users SET is_blocked=0 WHERE username=?", (username,))
            conn.commit()
