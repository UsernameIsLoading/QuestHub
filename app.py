import os, json, random, uuid, io
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, select, text

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['BACKUP_ADMIN_USERNAME'] = os.environ.get('BACKUP_ADMIN_USERNAME', '')
app.config['DATABASE_CREATED_AT'] = os.environ.get('DATABASE_CREATED_AT', '')
raw_db = os.environ.get('DATABASE_URL', 'sqlite:///questhub.db').strip()
# O pacote instala psycopg v3 (psycopg[binary]); force esse driver no SQLAlchemy.
# Sem isso, URLs postgresql:// podem tentar importar psycopg2, que não está instalado.
if raw_db.startswith('postgres://'):
    raw_db = raw_db.replace('postgres://', 'postgresql+psycopg://', 1)
elif raw_db.startswith('postgresql://'):
    raw_db = raw_db.replace('postgresql://', 'postgresql+psycopg://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = raw_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Entre na sua conta para continuar.'
login_manager.login_message_category = 'info'
csrf = CSRFProtect(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    statement = db.Column(db.Text, nullable=False)
    subject = db.Column(db.String(100), nullable=False, index=True)
    subject_code = db.Column(db.String(12), nullable=True)
    difficulty = db.Column(db.String(20), nullable=False, index=True)
    source = db.Column(db.String(200), nullable=False, default='Não informada', index=True)
    explanation = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    choices = db.relationship('Choice', backref='question', cascade='all, delete-orphan', order_by='Choice.position')

class SubjectCode(db.Model):
    __tablename__ = 'subject_code'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    creator = db.relationship('User')

class StudyMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_code = db.Column(db.String(12), nullable=False, index=True)
    subject = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # link, video, summary, formulas
    url = db.Column(db.String(1000))
    summary = db.Column(db.Text)
    formulas = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    author = db.relationship('User')

class Choice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False, index=True)
    choice_id = db.Column(db.Integer, db.ForeignKey('choice.id'), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    answered_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    mode = db.Column(db.String(10), nullable=False, default='study')
    question = db.relationship('Question')
    choice = db.relationship('Choice')

class ExamSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    question_ids = db.Column(db.Text, nullable=False)
    answers_json = db.Column(db.Text, nullable=False, default='{}')
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    duration_seconds = db.Column(db.Integer, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True))
    score = db.Column(db.Integer)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

class RegisterForm(FlaskForm):
    username = StringField('Nome de usuário', validators=[DataRequired(), Length(min=3, max=40)])
    password = PasswordField('Senha', validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField('Confirmar senha', validators=[DataRequired(), EqualTo('password', message='As senhas não coincidem.')])
    submit = SubmitField('Criar conta')
class LoginForm(FlaskForm):
    username = StringField('Nome de usuário', validators=[DataRequired(), Length(min=3, max=40)])
    password = PasswordField('Senha', validators=[DataRequired()])
    submit = SubmitField('Entrar')

@app.context_processor
def inject_globals():
    return {'now_utc': datetime.now(timezone.utc), 'backup_schedule': database_backup_schedule()}



def backup_admin_required():
    """Backups include account data; restrict them to the configured owner."""
    configured_admin = os.environ.get('BACKUP_ADMIN_USERNAME', '').strip().lower()
    return current_user.is_authenticated and bool(configured_admin) and current_user.username.lower() == configured_admin

def database_backup_schedule():
    """Return next 30-day cycle and reminder window based on configured DB creation date."""
    raw = os.environ.get('DATABASE_CREATED_AT', '').strip()
    if not raw:
        return {'configured': False, 'next_date': None, 'reminder': False, 'days_left': None}
    try:
        created = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(timezone.utc)
    except ValueError:
        return {'configured': False, 'next_date': None, 'reminder': False, 'days_left': None}
    cycle_days = max(1, int(os.environ.get('DATABASE_CYCLE_DAYS', '30')))
    now = datetime.now(timezone.utc)
    elapsed = max(0, (now - created).total_seconds())
    cycles_elapsed = int(elapsed // (cycle_days * 86400))
    next_date = created + timedelta(days=(cycles_elapsed + 1) * cycle_days)
    days_left = (next_date.date() - now.date()).days
    return {'configured': True, 'next_date': next_date, 'reminder': 0 <= days_left <= 1, 'days_left': days_left}

def filtered_questions(query):
    subject = request.args.get('subject', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    source = request.args.get('source', '').strip()
    code = request.args.get('code', '').strip().upper()
    if code: query = query.filter(Question.subject_code.ilike(f'%{code}%'))
    if subject: query = query.filter(Question.subject == subject)
    if difficulty in ('Fácil', 'Média', 'Difícil'): query = query.filter(Question.difficulty == difficulty)
    if source: query = query.filter(Question.source == source)
    return query

def question_options():
    return {
      'subjects': [r[0] for r in db.session.query(Question.subject).distinct().order_by(Question.subject).all()],
      'sources': [r[0] for r in db.session.query(Question.source).distinct().order_by(Question.source).all()],
      'difficulties': ['Fácil', 'Média', 'Difícil']
    }

def recent_status(user_id, question_id):
    attempt = Attempt.query.filter_by(user_id=user_id, question_id=question_id).order_by(Attempt.answered_at.desc()).first()
    if not attempt: return None
    answered_at = attempt.answered_at if attempt.answered_at.tzinfo else attempt.answered_at.replace(tzinfo=timezone.utc)
    return 'Respondida recentemente' if answered_at >= datetime.now(timezone.utc) - timedelta(days=7) else 'É bom relembrar'

@app.route('/')
def index():
    total = Question.query.count()
    subjects = db.session.query(Question.subject).distinct().count()
    return render_template('index.html', total=total, subjects=subjects)

@app.route('/register', methods=['GET','POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            flash('Nome de usuário já cadastrado.', 'error')
        else:
            # Campo interno mantido para compatibilidade com bancos já implantados; o usuário não precisa fornecer e-mail.
            internal_email = f'{uuid.uuid4().hex}@accounts.questhub.invalid'
            user = User(username=username, email=internal_email); user.set_password(form.password.data)
            db.session.add(user); db.session.commit(); login_user(user)
            flash('Conta criada. Bem-vindo!', 'success'); return redirect(url_for('dashboard'))
    return render_template('auth.html', form=form, mode='register')

@app.route('/login', methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(func.lower(User.username) == form.username.data.strip().lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True); return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Nome de usuário ou senha inválidos.', 'error')
    return render_template('auth.html', form=form, mode='login')

@app.route('/logout', methods=['POST'])
@login_required
def logout(): logout_user(); flash('Você saiu da conta.', 'info'); return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    attempts = Attempt.query.filter_by(user_id=current_user.id).all()
    total = len(attempts); correct = sum(a.is_correct for a in attempts)
    unique_answered = len({a.question_id for a in attempts})
    by_subject = {}
    for a in attempts:
        key = a.question.subject
        by_subject.setdefault(key, {'total': 0, 'correct': 0})
        by_subject[key]['total'] += 1; by_subject[key]['correct'] += int(a.is_correct)
    due = []
    latest = {}
    for a in sorted(attempts, key=lambda x: x.answered_at): latest[a.question_id] = a
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for qid, a in latest.items():
        when = a.answered_at if a.answered_at.tzinfo else a.answered_at.replace(tzinfo=timezone.utc)
        if when < cutoff:
            q = db.session.get(Question, qid)
            if q: due.append(q)
    return render_template('dashboard.html', total=total, correct=correct, pct=round(correct*100/total,1) if total else 0, unique_answered=unique_answered, by_subject=by_subject, due=due[:8])

@app.route('/questions')
def questions():
    query = filtered_questions(Question.query)
    qs = query.order_by(Question.created_at.desc()).all()
    statuses = {q.id: recent_status(current_user.id, q.id) for q in qs} if current_user.is_authenticated else {}
    return render_template('questions.html', questions=qs, opts=question_options(), statuses=statuses)

@app.route('/questions/new', methods=['GET','POST'])
@login_required
def new_question():
    if request.method == 'POST':
        statement = request.form.get('statement','').strip(); subject = request.form.get('subject','').strip()
        subject_code = request.form.get('subject_code','').strip().upper()
        difficulty = request.form.get('difficulty','').strip(); source = request.form.get('source','').strip() or 'Não informada'
        explanation = request.form.get('explanation','').strip()
        texts = [t.strip() for t in request.form.getlist('choice_text[]') if t.strip()]
        correct_index = request.form.get('correct_index','')
        if len(statement) < 5 or not subject or not subject_code or not __import__('re').fullmatch(r'[A-Z]{2,5}[0-9]{3}', subject_code) or difficulty not in ('Fácil','Média','Difícil') or len(texts) < 2:
            flash('Informe enunciado, assunto, código no formato FIS003, dificuldade e pelo menos duas alternativas.', 'error')
        elif not correct_index.isdigit() or int(correct_index) >= len(texts):
            flash('Selecione a alternativa correta.', 'error')
        else:
            q = Question(statement=statement, subject=subject, subject_code=subject_code, difficulty=difficulty, source=source, explanation=explanation or None, created_by=current_user.id)
            db.session.add(q); db.session.flush()
            correct = int(correct_index)
            for i, text in enumerate(texts): db.session.add(Choice(question_id=q.id, text=text, is_correct=(i==correct), position=i))
            db.session.commit(); flash('Questão adicionada ao banco!', 'success'); return redirect(url_for('question_detail', question_id=q.id))
    return render_template('question_new.html')

@app.route('/questions/<int:question_id>')
def question_detail(question_id):
    q = db.session.get(Question, question_id) or abort(404)
    status = recent_status(current_user.id, q.id) if current_user.is_authenticated else None
    return render_template('question_detail.html', q=q, status=status)

@app.route('/questions/<int:question_id>/answer', methods=['POST'])
@login_required
def answer_question(question_id):
    q = db.session.get(Question, question_id) or abort(404)
    try: choice_id = int(request.form.get('choice_id',''))
    except ValueError: abort(400)
    choice = Choice.query.filter_by(id=choice_id, question_id=q.id).first_or_404()
    attempt = Attempt(user_id=current_user.id, question_id=q.id, choice_id=choice.id, is_correct=choice.is_correct, mode='study')
    db.session.add(attempt); db.session.commit()
    return render_template('answer_result.html', q=q, choice=choice, correct=choice.is_correct)


@app.route('/subjects')
def subjects():
    codes = SubjectCode.query.order_by(SubjectCode.code).all()
    return render_template('subjects.html', codes=codes)

@app.route('/subjects/new', methods=['GET', 'POST'])
@login_required
def new_subject_code():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        valid_code = bool(__import__('re').fullmatch(r'[A-Z]{2,5}[0-9]{3}', code))
        if not valid_code or not name:
            flash('Use um código com 2–5 letras e 3 números (ex.: FIS003) e informe o nome do assunto.', 'error')
        elif SubjectCode.query.filter_by(code=code).first():
            flash(f'O código {code} já está cadastrado. Escolha outro ou reutilize o existente.', 'error')
        else:
            db.session.add(SubjectCode(code=code, name=name, created_by=current_user.id))
            db.session.commit()
            flash(f'Código {code} cadastrado com sucesso!', 'success')
            return redirect(url_for('materials', code=code))
    return render_template('subject_new.html')

@app.route('/materials')
def materials():
    code = request.args.get('code', '').strip().upper()
    subject = request.args.get('subject', '').strip()
    query = StudyMaterial.query
    if code: query = query.filter(StudyMaterial.subject_code.ilike(f'%{code}%'))
    if subject: query = query.filter(StudyMaterial.subject.ilike(f'%{subject}%'))
    items = query.order_by(StudyMaterial.subject_code, StudyMaterial.created_at.desc()).all()
    subjects = db.session.query(StudyMaterial.subject_code, StudyMaterial.subject).distinct().order_by(StudyMaterial.subject_code).all()
    return render_template('materials.html', materials=items, subjects=subjects, code=code, subject=subject)

@app.route('/materials/new', methods=['GET', 'POST'])
@login_required
def new_material():
    if request.method == 'POST':
        code = request.form.get('subject_code', '').strip().upper()
        subject = request.form.get('subject', '').strip()
        title = request.form.get('title', '').strip()
        kind = request.form.get('kind', '').strip()
        url = request.form.get('url', '').strip()
        summary = request.form.get('summary', '').strip()
        formulas = request.form.get('formulas', '').strip()
        valid_code = bool(__import__('re').fullmatch(r'[A-Z]{2,5}[0-9]{3}', code))
        valid_url = not url or (url.startswith('https://') or url.startswith('http://'))
        if not valid_code or not subject or not title or kind not in ('link', 'video', 'summary', 'formulas') or not valid_url:
            flash('Confira o código (ex.: FIS003), assunto, título, tipo e URL.', 'error')
        elif not (url or summary or formulas):
            flash('Adicione ao menos um link, resumo ou fórmula.', 'error')
        else:
            item = StudyMaterial(subject_code=code, subject=subject, title=title, kind=kind, url=url or None, summary=summary or None, formulas=formulas or None, created_by=current_user.id)
            db.session.add(item); db.session.commit()
            flash('Material de estudo adicionado!', 'success')
            return redirect(url_for('materials', code=code))
    return render_template('material_new.html')

@app.route('/leaderboard')
def leaderboard():
    users = User.query.order_by(User.username).all(); rows=[]
    for user in users:
        attempts = Attempt.query.filter_by(user_id=user.id).all()
        total = len(attempts); correct = sum(a.is_correct for a in attempts)
        rows.append({'username':user.username, 'total':total, 'correct':correct, 'pct':round(correct*100/total,1) if total else 0})
    rows.sort(key=lambda r:(r['pct'] if r['total'] else -1, r['total']), reverse=True)
    return render_template('leaderboard.html', rows=rows)

@app.route('/exam', methods=['GET','POST'])
@login_required
def exam_setup():
    opts = question_options()
    if request.method == 'POST':
        try: quantity = max(1, min(100, int(request.form.get('quantity','20')))); minutes = max(1, min(180, int(request.form.get('minutes','30'))))
        except ValueError: quantity, minutes = 20, 30
        query = Question.query
        subject=request.form.get('subject',''); difficulty=request.form.get('difficulty',''); source=request.form.get('source',''); code=request.form.get('code','').strip().upper()
        if code: query=query.filter(Question.subject_code.ilike(f'%{code}%'))
        if subject: query=query.filter_by(subject=subject)
        if difficulty in ('Fácil','Média','Difícil'): query=query.filter_by(difficulty=difficulty)
        if source: query=query.filter_by(source=source)
        pool=query.all()
        if not pool: flash('Nenhuma questão encontrada com esses filtros.', 'error'); return render_template('exam_setup.html', opts=opts)
        selected=random.sample(pool, min(quantity,len(pool)))
        exam=ExamSession(user_id=current_user.id, question_ids=json.dumps([q.id for q in selected]), duration_seconds=minutes*60)
        db.session.add(exam); db.session.commit(); return redirect(url_for('take_exam', exam_id=exam.id))
    return render_template('exam_setup.html', opts=opts)

@app.route('/exam/<int:exam_id>', methods=['GET','POST'])
@login_required
def take_exam(exam_id):
    exam=ExamSession.query.filter_by(id=exam_id,user_id=current_user.id).first_or_404()
    if exam.finished_at: return redirect(url_for('exam_result', exam_id=exam.id))
    started=exam.started_at if exam.started_at.tzinfo else exam.started_at.replace(tzinfo=timezone.utc)
    remaining=max(0, exam.duration_seconds-int((datetime.now(timezone.utc)-started).total_seconds()))
    qs=[db.session.get(Question,qid) for qid in json.loads(exam.question_ids)]
    qs=[q for q in qs if q]
    if request.method=='POST' or remaining <= 0:
        answers={}
        if request.method=='POST' and remaining>0:
            for q in qs:
                val=request.form.get(f'q_{q.id}')
                if val and val.isdigit() and any(c.id==int(val) for c in q.choices): answers[str(q.id)]=int(val)
        score=0
        for q in qs:
            cid=answers.get(str(q.id)); choice=next((c for c in q.choices if c.id==cid),None)
            if choice:
                db.session.add(Attempt(user_id=current_user.id,question_id=q.id,choice_id=choice.id,is_correct=choice.is_correct,mode='exam'))
                score += int(choice.is_correct)
        exam.answers_json=json.dumps(answers); exam.score=score; exam.finished_at=datetime.now(timezone.utc); db.session.commit()
        return redirect(url_for('exam_result', exam_id=exam.id))
    return render_template('take_exam.html', exam=exam, questions=qs, remaining=remaining)

@app.route('/exam/<int:exam_id>/result')
@login_required
def exam_result(exam_id):
    exam=ExamSession.query.filter_by(id=exam_id,user_id=current_user.id).first_or_404()
    if not exam.finished_at: return redirect(url_for('take_exam',exam_id=exam.id))
    answers=json.loads(exam.answers_json or '{}'); qs=[db.session.get(Question,qid) for qid in json.loads(exam.question_ids)]; qs=[q for q in qs if q]
    details=[]
    for q in qs:
        cid=answers.get(str(q.id)); chosen=next((c for c in q.choices if c.id==cid),None); correct=next((c for c in q.choices if c.is_correct),None)
        details.append({'q':q,'chosen':chosen,'correct':correct,'ok':bool(chosen and chosen.is_correct)})
    return render_template('exam_result.html', exam=exam, details=details, total=len(qs), pct=round((exam.score or 0)*100/len(qs),1) if qs else 0)

@app.route('/admin/backups', methods=['GET'])
@login_required
def backups_page():
    if not backup_admin_required():
        abort(403)
    schedule = database_backup_schedule()
    return render_template('backups.html', schedule=schedule, table_count=len(db.metadata.sorted_tables))

@app.route('/admin/backups/download', methods=['POST'])
@login_required
def download_backup():
    if not backup_admin_required():
        abort(403)
    tables = {}
    with db.engine.connect() as conn:
        for table in db.metadata.sorted_tables:
            rows = conn.execute(select(table)).mappings().all()
            tables[table.name] = [dict(row) for row in rows]
    # JSON format preserves every application table and explicit primary keys.
    payload = {
        'format': 'questhub-backup',
        'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'database_dialect': db.engine.dialect.name,
        'tables': tables,
    }
    stream = io.BytesIO(json.dumps(payload, ensure_ascii=False, default=lambda value: value.isoformat() if hasattr(value, 'isoformat') else str(value), indent=2).encode('utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return send_file(stream, mimetype='application/json', as_attachment=True, download_name=f'questhub-backup-{stamp}.json')

@app.route('/admin/backups/restore', methods=['POST'])
@login_required
def restore_backup():
    if not backup_admin_required():
        abort(403)
    upload = request.files.get('backup_file')
    if not upload or not upload.filename:
        flash('Selecione um arquivo JSON de backup.', 'error')
        return redirect(url_for('backups_page'))
    try:
        payload = json.load(upload.stream)
        if payload.get('format') != 'questhub-backup' or payload.get('version') != 1 or not isinstance(payload.get('tables'), dict):
            raise ValueError('Formato de backup não reconhecido.')
        expected = {table.name for table in db.metadata.sorted_tables}
        provided = set(payload['tables'])
        if not provided.issubset(expected) or not provided:
            raise ValueError('O arquivo contém tabelas incompatíveis com esta versão do QuestHub.')
        for table_name, rows in payload['tables'].items():
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f'Dados inválidos na tabela {table_name}.')
            table_obj = db.metadata.tables[table_name]
            allowed_columns = {column.name for column in table_obj.columns}
            if any(not set(row).issubset(allowed_columns) for row in rows):
                raise ValueError(f'Colunas inválidas na tabela {table_name}.')
            # Convert ISO strings back to native temporal values before binding to SQLAlchemy.
            for row in rows:
                for column in table_obj.columns:
                    value = row.get(column.name)
                    if value is None or not isinstance(value, str):
                        continue
                    try:
                        if str(column.type).upper().startswith('DATETIME') or column.type.__class__.__name__ == 'DateTime':
                            row[column.name] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        elif column.type.__class__.__name__ == 'Date':
                            from datetime import date
                            row[column.name] = date.fromisoformat(value)
                    except (ValueError, TypeError):
                        raise ValueError(f'Data inválida na coluna {table_name}.{column.name}.')
        # A restore replaces application records. Transaction rollback protects against partial restores.
        with db.engine.begin() as conn:
            for table in reversed(db.metadata.sorted_tables):
                conn.execute(table.delete())
            for table in db.metadata.sorted_tables:
                rows = payload['tables'].get(table.name, [])
                if rows:
                    conn.execute(table.insert(), rows)
            if db.engine.dialect.name == 'postgresql':
                for table in db.metadata.sorted_tables:
                    pk = list(table.primary_key.columns)
                    if len(pk) == 1 and isinstance(pk[0].type, db.Integer):
                        seq = conn.execute(text("SELECT pg_get_serial_sequence(:table_name, :column_name)"), {'table_name': table.name, 'column_name': pk[0].name}).scalar()
                        if seq:
                            conn.execute(text("SELECT setval(:seq, COALESCE((SELECT MAX(" + pk[0].name + ") FROM " + table.name + "), 1), EXISTS (SELECT 1 FROM " + table.name + "))"), {'seq': seq})
        flash('Backup restaurado com sucesso. Os dados atuais foram substituídos pelos dados do arquivo.', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Falha ao restaurar backup QuestHub')
        flash(f'Não foi possível restaurar o backup: {exc}', 'error')
    return redirect(url_for('backups_page'))

@app.errorhandler(400)
def bad_request(e):
    return render_template('error.html', title='Solicitação inválida', message='Confira os dados enviados e tente novamente.'), 400

with app.app_context():
    db.create_all()
    # Migração leve para instalações já existentes no Render/SQLite.
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if 'question' in inspector.get_table_names() and 'subject_code' not in {c['name'] for c in inspector.get_columns('question')}:
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE question ADD COLUMN subject_code VARCHAR(12)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_question_subject_code ON question (subject_code)'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG') == '1')
