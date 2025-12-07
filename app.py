# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Voter, Nominee, Vote, Admin, Config
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///instance/app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Инициализация БД и админа при первом запуске
@app.before_first_request
def init_db():
    db.create_all()
    if not Admin.query.first():
        admin = Admin(username='admin')
        admin.set_password('admin')  # ⚠️ Смените в продакшене!
        db.session.add(admin)
    if not Config.query.first():
        db.session.add(Config(voting_active=False))
    db.session.commit()

# ------------------ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ------------------
def get_scores():
    nominees = Nominee.query.all()
    score_data = {}
    first_place_counts = {}

    for n in nominees:
        score_data[n.name] = 0
        first_place_counts[n.name] = 0

    votes = Vote.query.all()
    for v in votes:
        first = Nominee.query.get(v.first_id).name
        second = Nominee.query.get(v.second_id).name
        third = Nominee.query.get(v.third_id).name

        score_data[first] += 3
        score_data[second] += 2
        score_data[third] += 1
        first_place_counts[first] += 1

    # Сортировка: сначала по очкам, потом по количеству первых мест
    sorted_scores = sorted(
        score_data.items(),
        key=lambda x: (x[1], first_place_counts[x[0]]),
        reverse=True
    )
    return sorted_scores, first_place_counts

# ------------------ МАРШРУТЫ ------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('vote'))
    if 'admin' in session:
        return redirect(url_for('admin_panel'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Попробуем как админа
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session['admin'] = True
            return redirect(url_for('admin_panel'))

        # Попробуем как голосующего
        voter = Voter.query.filter_by(username=username).first()
        if voter and voter.check_password(password):
            if voter.has_voted:
                flash('Вы уже проголосовали.', 'info')
                return redirect(url_for('vote_result'))
            session['user_id'] = voter.id
            session['username'] = voter.username
            return redirect(url_for('vote'))

        flash('Неверный логин или пароль.', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ------------------ ГОЛОСОВАНИЕ ------------------

@app.route('/vote', methods=['GET', 'POST'])
def vote():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    voter = Voter.query.get(session['user_id'])
    if voter.has_voted:
        return redirect(url_for('vote_result'))

    config = Config.query.first()
    if not config or not config.voting_active:
        flash('Голосование сейчас не активно.', 'info')
        return redirect(url_for('login'))

    nominees = Nominee.query.all()
    if len(nominees) < 3:
        flash('Недостаточно номинантов для голосования (минимум 3).', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        first = request.form.get('first')
        second = request.form.get('second')
        third = request.form.get('third')

        if not all([first, second, third]):
            flash('Выберите всех трёх кандидатов.', 'error')
            return redirect(url_for('vote'))

        if len({first, second, third}) != 3:
            flash('Кандидаты должны быть разными.', 'error')
            return redirect(url_for('vote'))

        try:
            vote = Vote(
                voter_id=voter.id,
                first_id=int(first),
                second_id=int(second),
                third_id=int(third)
            )
            voter.has_voted = True
            db.session.add(vote)
            db.session.commit()
            flash('Ваш голос учтён! Спасибо!', 'success')
            return redirect(url_for('vote_result'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при голосовании. Попробуйте снова.', 'error')

    return render_template('vote.html', nominees=nominees)

@app.route('/vote_result')
def vote_result():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    scores, first_counts = get_scores()
    return render_template('vote.html', scores=scores, show_results=True)

# ------------------ АДМИНКА ------------------

@app.route('/admin')
def admin_panel():
    if 'admin' not in session:
        return redirect(url_for('login'))

    config = Config.query.first()
    active = config.voting_active if config else False
    nominees = [n.name for n in Nominee.query.all()]
    voters = [v.username for v in Voter.query.all()]
    scores, first_counts = get_scores()

    return render_template('admin.html',
                           active=active,
                           nominees=nominees,
                           voters=voters,
                           scores=scores)

@app.route('/admin/start', methods=['POST'])
def start_voting():
    if 'admin' not in session:
        return redirect(url_for('login'))
    config = Config.query.first()
    config.voting_active = True
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/end', methods=['POST'])
def end_voting():
    if 'admin' not in session:
        return redirect(url_for('login'))
    config = Config.query.first()
    config.voting_active = False
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_nominee', methods=['POST'])
def add_nominee():
    if 'admin' not in session:
        return redirect(url_for('login'))
    name = request.form['name'].strip()
    if name and not Nominee.query.filter_by(name=name).first():
        db.session.add(Nominee(name=name))
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_voter', methods=['POST'])
def add_voter():
    if 'admin' not in session:
        return redirect(url_for('login'))
    username = request.form['username'].strip()
    password = request.form['password']
    if username and password and not Voter.query.filter_by(username=username).first():
        voter = Voter(username=username)
        voter.set_password(password)
        db.session.add(voter)
        db.session.commit()
    return redirect(url_for('admin_panel'))

# ------------------ ЗАПУСК ------------------

if __name__ == '__main__':
    app.run(debug=True)
