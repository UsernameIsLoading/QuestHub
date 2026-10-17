import os, json, random, uuid, io, re
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
    review_status = db.Column(db.String(30), nullable=False, default='Revisada', index=True)
    question_type = db.Column(db.String(24), nullable=False, default='multiple_choice', index=True)
    expected_answer = db.Column(db.Text)
    ai_generated = db.Column(db.Boolean, nullable=False, default=False, index=True)
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

class EssayResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False, index=True)
    answer_text = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    question = db.relationship('Question')

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
    review = request.args.get('review', '').strip()
    code = request.args.get('code', '').strip().upper()
    if code: query = query.filter(Question.subject_code.ilike(f'%{code}%'))
    if subject: query = query.filter(Question.subject == subject)
    if difficulty in ('Fácil', 'Média', 'Difícil'): query = query.filter(Question.difficulty == difficulty)
    if source: query = query.filter(Question.source == source)
    if review in ('Revisada', 'Não revisada'): query = query.filter(Question.review_status == review)
    return query

def question_options():
    return {
      'subjects': [r[0] for r in db.session.query(Question.subject).distinct().order_by(Question.subject).all()],
      'sources': [r[0] for r in db.session.query(Question.source).distinct().order_by(Question.source).all()],
      'difficulties': ['Fácil', 'Média', 'Difícil']
    }

def gemini_json(system_prompt, user_prompt, schema_name, schema):
    """Call Gemini server-side using JSON output; API key stays on the server."""
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('A chave GEMINI_API_KEY não está configurada no servidor.')
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash'),
        contents=f'{system_prompt}\n\n{user_prompt}',
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema=schema,
            temperature=0.2,
        ),
    )
    content = getattr(response, 'text', None)
    if not content:
        raise RuntimeError('O Gemini não retornou conteúdo. Tente novamente.')
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError('O Gemini retornou uma resposta JSON inválida.') from exc

QUESTION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'questions': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'number': {'type': 'integer'}, 'statement': {'type': 'string'},
            'question_type': {'type': 'string', 'enum': ['multiple_choice', 'essay']},
            'choices': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'properties': {'label': {'type': 'string'}, 'text': {'type': 'string'}}, 'required': ['label', 'text']}},
            'correct_label': {'type': 'string'}, 'expected_answer': {'type': 'string'},
            'explanation': {'type': 'string'},
        }, 'required': ['number', 'statement', 'question_type', 'choices', 'correct_label', 'expected_answer', 'explanation']
    }}}
    , 'required': ['questions']
}

FEEDBACK_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'suggested_answer': {'type': 'string'}, 'assessment': {'type': 'string'},
                   'explanation': {'type': 'string'}, 'confidence': {'type': 'string', 'enum': ['baixa', 'média', 'alta']}},
    'required': ['suggested_answer', 'assessment', 'explanation', 'confidence']
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
    total = len(attempts); correct = sum(a.is_correct is True for a in attempts)
    unique_answered = len({a.question_id for a in attempts})
    by_subject = {}
    for a in attempts:
        key = a.question.subject
        by_subject.setdefault(key, {'total': 0, 'correct': 0})
        by_subject[key]['total'] += 1; by_subject[key]['correct'] += int(a.is_correct is True)
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


@app.route('/questions/import', methods=['GET', 'POST'])
@login_required
def import_questions():
    """Bulk-import questions from a text-based PDF and a separate/pasted answer key."""
    import re
    from werkzeug.utils import secure_filename
    if request.method == 'POST':
        pdf = request.files.get('pdf_file')
        subject = (request.form.get('subject') or 'Questões importadas').strip()[:100]
        subject_code = (request.form.get('subject_code') or 'IMP001').strip().upper()
        difficulty = request.form.get('difficulty', 'Média')
        source = (request.form.get('source') or 'PDF importado').strip()[:200]
        answer_text = request.form.get('answer_key', '')
        answer_pdf = request.files.get('answer_pdf')
        selected_type = request.form.get('question_type', 'multiple_choice')
        if selected_type not in ('multiple_choice', 'essay'):
            selected_type = 'multiple_choice'
        if not pdf or not pdf.filename.lower().endswith('.pdf'):
            flash('Selecione um arquivo PDF.', 'error')
            return render_template('import_questions.html')
        if not re.fullmatch(r'[A-Z]{2,5}[0-9]{3}', subject_code):
            flash('O código deve seguir o formato FIS003 (2–5 letras e 3 números).', 'error')
            return render_template('import_questions.html')
        if difficulty not in ('Fácil', 'Média', 'Difícil'):
            difficulty = 'Média'
        # Primeiro tenta extrair texto digital. Páginas sem texto útil passam pelo OCR.
        used_ocr = False
        try:
            from pypdf import PdfReader
            from io import BytesIO
            pdf_bytes = pdf.read()
            reader = PdfReader(BytesIO(pdf_bytes))
            pages = []
            for page in reader.pages:
                pages.append((page.extract_text() or '').strip())

            # OCR só nas páginas sem texto selecionável, mantendo a ordem original.
            pages_needing_ocr = [i for i, page_text in enumerate(pages) if len(page_text) < 30]
            if pages_needing_ocr:
                try:
                    import fitz  # PyMuPDF: renderiza páginas do PDF sem depender do Poppler.
                    import pytesseract
                    import shutil
                    from PIL import Image, ImageOps, ImageFilter
                    tess_cmd = shutil.which('tesseract')
                    if not tess_cmd:
                        raise RuntimeError('Executável tesseract ausente. Configure o build do Render para instalar tesseract-ocr e tesseract-ocr-por.')
                    pytesseract.pytesseract.tesseract_cmd = tess_cmd
                    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
                    for page_index in pages_needing_ocr:
                        page = doc.load_page(page_index)
                        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                        image = Image.open(BytesIO(pix.tobytes('png'))).convert('L')
                        image = ImageOps.autocontrast(image).filter(ImageFilter.SHARPEN)
                        try:
                            langs = pytesseract.get_languages(config='')
                            lang = 'por+eng' if 'por' in langs and 'eng' in langs else ('por' if 'por' in langs else 'eng')
                            # Layouts de prova variam; tenta dois modos e conserva o texto mais legível.
                            candidates = [pytesseract.image_to_string(image, lang=lang, config=f'--oem 3 --psm {psm}') for psm in (3, 6)]
                            ocr_text = max(candidates, key=lambda value: sum(ch.isalnum() for ch in value))
                        except Exception as lang_exc:
                            raise RuntimeError('Tesseract foi encontrado, mas falhou ao carregar idiomas OCR: ' + str(lang_exc)[:140])
                        pages[page_index] = ocr_text.strip()
                        used_ocr = used_ocr or len(ocr_text.strip()) > 0
                    doc.close()
                except Exception as ocr_exc:
                    flash('O OCR não conseguiu processar uma ou mais páginas escaneadas. O deploy precisa instalar o executável Tesseract e os idiomas por/eng. Detalhe: ' + str(ocr_exc)[:220], 'error')
                    return render_template('import_questions.html')
            full_text = '\n'.join(pages)
        except Exception as exc:
            flash('Não foi possível ler o PDF. Verifique se ele não está corrompido. Detalhe: ' + str(exc)[:180], 'error')
            return render_template('import_questions.html')
        if len(full_text.strip()) < 30:
            flash('Não foi possível extrair texto suficiente do PDF, mesmo após tentar OCR. Verifique a qualidade/resolução das páginas.', 'error')
            return render_template('import_questions.html')
        if used_ocr:
            flash('OCR foi usado em uma ou mais páginas. Como o reconhecimento pode confundir letras e números, as questões importadas deste PDF serão marcadas como “Não revisada”.', 'info')
        # O gabarito pode ser colado no campo de texto ou enviado em PDF separado.
        answer_pdf_text = ''
        if answer_pdf and answer_pdf.filename:
            if not answer_pdf.filename.lower().endswith('.pdf'):
                flash('O arquivo de gabarito separado precisa estar em PDF.', 'error')
                return render_template('import_questions.html')
            try:
                from pypdf import PdfReader
                from io import BytesIO
                answer_pdf_bytes = answer_pdf.read()
                answer_reader = PdfReader(BytesIO(answer_pdf_bytes))
                answer_pages = [(page.extract_text() or '').strip() for page in answer_reader.pages]
                answer_pdf_text = '\n'.join(answer_pages)
                # Tenta OCR quando o gabarito for escaneado ou não tiver texto selecionável.
                if len(answer_pdf_text.strip()) < 5:
                    try:
                        import fitz, pytesseract, shutil
                        from PIL import Image, ImageOps, ImageFilter
                        tess_cmd = shutil.which('tesseract')
                        if not tess_cmd:
                            raise RuntimeError('Tesseract não está instalado no servidor.')
                        pytesseract.pytesseract.tesseract_cmd = tess_cmd
                        answer_doc = fitz.open(stream=answer_pdf_bytes, filetype='pdf')
                        ocr_pages = []
                        for page in answer_doc:
                            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                            image = ImageOps.autocontrast(Image.open(BytesIO(pix.tobytes('png'))).convert('L')).filter(ImageFilter.SHARPEN)
                            try:
                                langs = pytesseract.get_languages(config='')
                                lang = 'por+eng' if 'por' in langs and 'eng' in langs else ('por' if 'por' in langs else 'eng')
                                txt = pytesseract.image_to_string(image, lang=lang, config='--oem 3 --psm 6')
                            except Exception:
                                txt = pytesseract.image_to_string(image, config='--oem 3 --psm 6')
                            ocr_pages.append(txt.strip())
                        answer_doc.close()
                        answer_pdf_text = '\n'.join(ocr_pages)
                    except Exception as ocr_key_exc:
                        raise RuntimeError('Não foi possível extrair o gabarito em texto nem por OCR: ' + str(ocr_key_exc)[:160])
                if len(answer_pdf_text.strip()) < 5:
                    flash('Não consegui extrair texto suficiente do PDF de gabarito. Confira a qualidade do arquivo ou cole as respostas no campo de texto.', 'error')
                    return render_template('import_questions.html')
            except Exception as key_exc:
                flash('Não foi possível ler o PDF de gabarito: ' + str(key_exc)[:180], 'error')
                return render_template('import_questions.html')
        answer_text = (answer_text or '') + '\n' + answer_pdf_text
        if request.form.get('ai_process') == 'yes':
            try:
                parsed = gemini_json(
                    'Você organiza questões educacionais extraídas de PDFs. Preserve fielmente o texto, não invente dados ausentes e não deduza gabaritos sem evidência. Analise o gabarito fornecido separadamente, associe os números às questões e confira se as letras correspondem às alternativas disponíveis. Se houver conflito, ambiguidade ou resposta ilegível, não escolha silenciosamente: deixe correct_label vazio. Para questão objetiva, use labels A-E; para discursivas, deixe expected_answer vazio se não houver resposta de referência. Retorne somente o schema solicitado.',
                    f'Tipo solicitado: {selected_type}. Matéria: {subject}. Dificuldade padrão: {difficulty}. Texto extraído do PDF (pode conter erros de OCR):\n{full_text[:45000]}\nGabarito informado pelo usuário (se houver):\n{answer_text[:10000]}',
                    'questhub_pdf_questions', QUESTION_SCHEMA)
                preview = []
                for item in parsed.get('questions', [])[:100]:
                    statement = str(item.get('statement', '')).strip()[:10000]
                    qtype = item.get('question_type')
                    choices = item.get('choices', []) if qtype == 'multiple_choice' else []
                    if len(statement) < 10 or qtype not in ('multiple_choice', 'essay'):
                        continue
                    if selected_type != qtype:
                        qtype = selected_type
                        choices = [] if qtype == 'essay' else choices
                    if qtype == 'multiple_choice':
                        choices = [{'label': str(c.get('label',''))[:2].upper(), 'text': str(c.get('text','')).strip()[:3000]} for c in choices[:5] if str(c.get('text','')).strip()]
                        if len(choices) < 2: continue
                    preview.append({'number': int(item.get('number', len(preview)+1)), 'statement': statement,
                                    'question_type': qtype, 'choices': choices,
                                    'correct_label': str(item.get('correct_label','')).strip().upper()[:2],
                                    'expected_answer': str(item.get('expected_answer','')).strip()[:5000],
                                    'explanation': str(item.get('explanation','')).strip()[:5000]})
                if not preview:
                    raise RuntimeError('A IA não identificou questões válidas. Tente o importador tradicional ou revise o PDF.')
                return render_template('ai_preview.html', items=preview, mode='import', subject=subject,
                                       subject_code=subject_code, difficulty=difficulty, source=source,
                                       used_ocr=used_ocr, back_url=url_for('import_questions'))
            except Exception as ai_exc:
                app.logger.exception('Falha no processamento IA do PDF')
                flash('O processamento por IA falhou: ' + str(ai_exc)[:240] + ' O importador tradicional continua disponível.', 'error')
                return render_template('import_questions.html')
        # Answer keys like "1-A 2-C", "1. A", or one answer per line.
        answer_text = (answer_text or '') + '\n' + full_text
        answers = {}
        for m in re.finditer(r'(?im)(?:quest[aã]o\s*)?(\d{1,4})\s*[\.\)\-:]\s*([A-E])\b', answer_text):
            answers[int(m.group(1))] = m.group(2).upper()
        # Separate question body from a trailing answer-key section where possible.
        body = re.split(r'(?im)^\s*(?:gabarito|respostas?\s+corretas)\s*:?\s*$', full_text)[0]
        starts = list(re.finditer(r'(?m)^\s*(\d{1,4})\s*[\.\)]\s+', body))
        if not starts:
            flash('Não consegui identificar a numeração das questões. Nenhuma questão foi importada.', 'error')
            return render_template('import_questions.html')
        imported = uncertain = duplicates = 0
        seen = set()
        for idx, start in enumerate(starts):
            qnum = int(start.group(1))
            end = starts[idx+1].start() if idx+1 < len(starts) else len(body)
            chunk = body[start.end():end].strip()
            # O tipo vem da escolha explícita no formulário, não da inferência do parser.
            option_matches = list(re.finditer(r'(?im)(?:^|\n)\s*(?:\(([A-E])\)|([A-E])[\)\.])\s+', chunk)) if selected_type == 'multiple_choice' else []
            statement = chunk[:option_matches[0].start()].strip() if option_matches else chunk
            choices = []
            for oi, om in enumerate(option_matches):
                label = (om.group(1) or om.group(2)).upper()
                cend = option_matches[oi+1].start() if oi+1 < len(option_matches) else len(chunk)
                ctext = chunk[om.end():cend].strip()
                if ctext:
                    choices.append((label, ctext))
            statement = re.sub(r'\s+', ' ', statement).strip()
            norm = re.sub(r'\W+', '', statement.lower())
            if len(statement) < 15 or norm in seen:
                duplicates += 1
                continue
            seen.add(norm)
            valid_choices = len(choices) >= 2 and len(choices) <= 5
            # Não cria questão objetiva sem alternativas: evita quebrar simulados.
            if selected_type == 'multiple_choice' and not valid_choices:
                duplicates += 1
                continue
            correct_label = answers.get(qnum) if selected_type == 'multiple_choice' else None
            labels = [c[0] for c in choices]
            question_type = selected_type
            status = 'Não revisada' if (used_ocr or len(statement) < 35 or (selected_type == 'multiple_choice' and (not correct_label or correct_label not in labels))) else 'Revisada'
            q = Question(statement=statement, subject=subject, subject_code=subject_code,
                         difficulty=difficulty, source=source, created_by=current_user.id,
                         review_status=status, question_type=question_type,
                         expected_answer=None,
                         explanation='Importada automaticamente do PDF. Confira o enunciado, as alternativas e o gabarito.' if status == 'Não revisada' else None)
            db.session.add(q); db.session.flush()
            if selected_type == 'multiple_choice':
                for pos, (label, ctext) in enumerate(choices):
                    db.session.add(Choice(question_id=q.id, text=ctext,
                                          is_correct=(correct_label is not None and label == correct_label),
                                          position=pos))
            imported += 1
            if status == 'Não revisada': uncertain += 1
        db.session.commit()
        skipped_note = ' ignorada(s) por duplicidade, extração inválida ou falta de alternativas (em múltipla escolha).'
        flash(f'Importação concluída: {imported} questão(ões) adicionada(s), {uncertain} marcada(s) como “Não revisada” e {duplicates}' + skipped_note, 'success')
        return redirect(url_for('questions', review='Não revisada'))
    return render_template('import_questions.html')

@app.route('/questions/ai/import/approve', methods=['POST'])
@login_required
def approve_ai_import():
    try:
        items = json.loads(request.form.get('items_json', '[]'))
    except (ValueError, TypeError):
        abort(400)
    subject = (request.form.get('subject') or '').strip()[:100]
    subject_code = (request.form.get('subject_code') or '').strip().upper()
    difficulty = request.form.get('difficulty', 'Média')
    source = (request.form.get('source') or 'PDF importado').strip()[:200]
    if not subject or not re.fullmatch(r'[A-Z]{2,5}[0-9]{3}', subject_code) or difficulty not in ('Fácil','Média','Difícil') or not isinstance(items, list) or not items or len(items) > 100:
        abort(400)
    saved = 0
    for item in items:
        if not isinstance(item, dict): continue
        statement = str(item.get('statement', '')).strip()[:10000]
        qtype = item.get('question_type')
        if len(statement) < 10 or qtype not in ('multiple_choice','essay'): continue
        choices = item.get('choices', []) if qtype == 'multiple_choice' else []
        correct_label = str(item.get('correct_label','')).strip().upper()
        labels = [str(c.get('label','')).strip().upper() for c in choices if isinstance(c,dict)]
        if qtype == 'multiple_choice' and (len(choices) < 2 or len(choices) > 5): continue
        has_key = qtype == 'multiple_choice' and correct_label in labels
        status = 'Revisada' if has_key or (qtype == 'essay' and bool(str(item.get('expected_answer','')).strip())) else 'Não revisada'
        q = Question(statement=statement, subject=subject, subject_code=subject_code, difficulty=difficulty,
                     source=source, created_by=current_user.id, review_status=status, question_type=qtype,
                     expected_answer=(str(item.get('expected_answer','')).strip() or None) if qtype == 'essay' else None,
                     explanation=(str(item.get('explanation','')).strip() or 'Texto organizado com auxílio de IA; confira antes de usar.')[:5000])
        db.session.add(q); db.session.flush()
        if qtype == 'multiple_choice':
            for pos, choice in enumerate(choices):
                if not isinstance(choice,dict) or not str(choice.get('text','')).strip(): continue
                label = str(choice.get('label','')).strip().upper()
                db.session.add(Choice(question_id=q.id, text=str(choice.get('text','')).strip()[:3000], is_correct=bool(has_key and label == correct_label), position=pos))
        saved += 1
    db.session.commit()
    flash(f'Prévia aprovada: {saved} questão(ões) salva(s). Confira os itens marcados como “Não revisada”.', 'success')
    return redirect(url_for('questions', subject=subject))

@app.route('/questions/<int:question_id>/ai-correct', methods=['POST'])
@login_required
def ai_correct_question(question_id):
    q = db.session.get(Question, question_id) or abort(404)
    answer = (request.form.get('answer_text') or '').strip()[:12000]
    choice_id = request.form.get('choice_id', '').strip()
    if choice_id:
        try: selected = Choice.query.filter_by(id=int(choice_id), question_id=q.id).first_or_404()
        except ValueError: abort(400)
        answer = selected.text
    if not answer:
        flash('Envie sua resposta antes de pedir a correção por IA.', 'error')
        return redirect(url_for('question_detail', question_id=q.id))
    if q.question_type == 'multiple_choice' and any(c.is_correct for c in q.choices):
        flash('Esta questão já possui gabarito cadastrado; use a correção normal.', 'info')
        return redirect(url_for('question_detail', question_id=q.id))
    try:
        choices_text = '\n'.join(f'{chr(65+i)}. {c.text}' for i,c in enumerate(q.choices))
        result = gemini_json(
            'Você é um avaliador educacional cuidadoso. Avalie a resposta do estudante com base no enunciado e em conhecimento confiável. Se faltar contexto, avise. Não finja que existe gabarito oficial. Dê feedback formativo, não apenas certo/errado.',
            f'Enunciado: {q.statement}\nAlternativas (se houver):\n{choices_text}\nResposta de referência cadastrada (se houver): {q.expected_answer or "nenhuma"}\nExplicação existente: {q.explanation or "nenhuma"}\nResposta do estudante: {answer}\nMatéria: {q.subject}',
            'questhub_ai_feedback', FEEDBACK_SCHEMA)
        return render_template('ai_feedback.html', q=q, answer=answer, result=result)
    except Exception as exc:
        app.logger.exception('Falha na correção por IA')
        flash('Não foi possível corrigir com IA agora: ' + str(exc)[:220], 'error')
        return redirect(url_for('question_detail', question_id=q.id))

@app.route('/subjects/<path:subject>/ai-create', methods=['GET','POST'])
@login_required
def create_ai_questions(subject):
    subject = subject.strip()[:100]
    existing = Question.query.filter(Question.subject == subject).count()
    if existing <= 10:
        flash('A criação com IA aparece quando o assunto tem mais de 10 questões cadastradas.', 'info')
        return redirect(url_for('questions', subject=subject))
    sample = Question.query.filter(Question.subject == subject).order_by(Question.created_at.desc()).limit(15).all()
    if request.method == 'POST':
        try: amount = max(1, min(10, int(request.form.get('amount', '5'))))
        except ValueError: amount = 5
        kind = request.form.get('question_type', 'multiple_choice')
        if kind not in ('multiple_choice','essay'): kind = 'multiple_choice'
        context = '\n\n'.join([f'Questão existente: {q.statement}\nAlternativas: ' + '; '.join(c.text for c in q.choices) for q in sample])
        try:
            parsed = gemini_json(
                'Crie questões educacionais originais em português, alinhadas ao assunto e ao nível inferido dos exemplos. Não copie literalmente os exemplos. Para múltipla escolha, crie 4 alternativas e um único gabarito correto. Para discursivas, não inclua alternativas. Explicações devem ser concisas. Retorne apenas o schema.',
                f'Assunto: {subject}. Tipo: {kind}. Quantidade: {amount}. Exemplos de questões já existentes para orientar escopo e dificuldade:\n{context[:18000]}',
                'questhub_generated_questions', QUESTION_SCHEMA)
            items=[]
            for item in parsed.get('questions',[])[:amount]:
                statement=str(item.get('statement','')).strip()[:10000]
                qtype=kind
                choices=item.get('choices',[]) if kind=='multiple_choice' else []
                if len(statement)<10: continue
                if kind=='multiple_choice':
                    choices=[{'label':str(c.get('label',''))[:2].upper(), 'text':str(c.get('text','')).strip()[:3000]} for c in choices[:5] if str(c.get('text','')).strip()]
                    if len(choices)<2: continue
                items.append({'number':len(items)+1,'statement':statement,'question_type':qtype,'choices':choices,
                              'correct_label':str(item.get('correct_label','')).strip().upper()[:2],
                              'expected_answer':str(item.get('expected_answer','')).strip()[:5000],
                              'explanation':str(item.get('explanation','')).strip()[:5000]})
            if not items: raise RuntimeError('A IA não retornou questões válidas. Tente novamente.')
            return render_template('ai_preview.html', items=items, mode='generated', subject=subject,
                                   subject_code=(sample[0].subject_code or 'IA001'), difficulty=(sample[0].difficulty or 'Média'),
                                   source='Elaborada por IA', back_url=url_for('questions', subject=subject))
        except Exception as exc:
            app.logger.exception('Falha ao criar questões por IA')
            flash('Não foi possível criar questões com IA: ' + str(exc)[:240], 'error')
    return render_template('ai_create.html', subject=subject, existing=existing)

@app.route('/questions/ai/generated/approve', methods=['POST'])
@login_required
def approve_ai_generated():
    try: items=json.loads(request.form.get('items_json','[]'))
    except (ValueError, TypeError): abort(400)
    subject=(request.form.get('subject') or '').strip()[:100]
    subject_code=(request.form.get('subject_code') or 'IA001').strip().upper()
    difficulty=request.form.get('difficulty','Média')
    if not subject or not re.fullmatch(r'[A-Z]{2,5}[0-9]{3}',subject_code) or difficulty not in ('Fácil','Média','Difícil') or not isinstance(items,list) or not items or len(items)>10: abort(400)
    saved=0
    for item in items:
        statement=str(item.get('statement','')).strip()[:10000] if isinstance(item,dict) else ''
        qtype=item.get('question_type') if isinstance(item,dict) else None
        if len(statement)<10 or qtype not in ('multiple_choice','essay'): continue
        choices=item.get('choices',[]) if qtype=='multiple_choice' else []
        correct_label=str(item.get('correct_label','')).strip().upper()
        labels=[str(c.get('label','')).strip().upper() for c in choices if isinstance(c,dict)]
        if qtype=='multiple_choice' and (len(choices)<2 or len(choices)>5): continue
        has_key=qtype=='multiple_choice' and correct_label in labels
        q=Question(statement=statement,subject=subject,subject_code=subject_code,difficulty=difficulty,source='Elaborada por IA',
                   created_by=current_user.id,review_status='Não revisada',question_type=qtype,ai_generated=True,
                   expected_answer=(str(item.get('expected_answer','')).strip() or None) if qtype=='essay' else None,
                   explanation=(str(item.get('explanation','')).strip() or None))
        db.session.add(q); db.session.flush()
        for pos,c in enumerate(choices if qtype=='multiple_choice' else []):
            if not isinstance(c,dict) or not str(c.get('text','')).strip(): continue
            label=str(c.get('label','')).strip().upper()
            db.session.add(Choice(question_id=q.id,text=str(c.get('text','')).strip()[:3000],is_correct=bool(has_key and label==correct_label),position=pos))
        saved+=1
    db.session.commit()
    flash(f'{saved} questão(ões) elaborada(s) por IA foram salvas com a tag “Elaborada por IA” e marcadas para revisão.', 'success')
    return redirect(url_for('questions', subject=subject))

@app.route('/questions')
def questions():
    query = filtered_questions(Question.query)
    qs = query.order_by(Question.created_at.desc()).all()
    statuses = {q.id: recent_status(current_user.id, q.id) for q in qs} if current_user.is_authenticated else {}
    selected_subject = request.args.get('subject', '').strip()
    selected_subject_count = Question.query.filter_by(subject=selected_subject).count() if selected_subject else 0
    return render_template('questions.html', questions=qs, opts=question_options(), statuses=statuses, selected_subject=selected_subject, selected_subject_count=selected_subject_count)

@app.route('/questions/new', methods=['GET','POST'])
@login_required
def new_question():
    if request.method == 'POST':
        statement = request.form.get('statement','').strip(); subject = request.form.get('subject','').strip()
        subject_code = request.form.get('subject_code','').strip().upper()
        difficulty = request.form.get('difficulty','').strip(); source = request.form.get('source','').strip() or 'Não informada'
        explanation = request.form.get('explanation','').strip()
        question_type = request.form.get('question_type','multiple_choice')
        expected_answer = request.form.get('expected_answer','').strip()
        texts = [t.strip() for t in request.form.getlist('choice_text[]') if t.strip()]
        correct_index = request.form.get('correct_index','')
        valid_base = len(statement) >= 5 and bool(subject) and bool(subject_code) and bool(__import__('re').fullmatch(r'[A-Z]{2,5}[0-9]{3}', subject_code)) and difficulty in ('Fácil','Média','Difícil')
        if not valid_base or question_type not in ('multiple_choice','essay'):
            flash('Informe enunciado, assunto, código FIS003 válido e dificuldade.', 'error')
        elif question_type == 'multiple_choice' and (len(texts) < 2 or not correct_index.isdigit() or int(correct_index) >= len(texts)):
            flash('Questões de múltipla escolha precisam de pelo menos duas alternativas e um gabarito.', 'error')
        else:
            q = Question(statement=statement, subject=subject, subject_code=subject_code, difficulty=difficulty, source=source,
                         explanation=explanation or None, created_by=current_user.id, question_type=question_type,
                         expected_answer=(expected_answer or None) if question_type == 'essay' else None)
            db.session.add(q); db.session.flush()
            if question_type == 'multiple_choice':
                correct = int(correct_index)
                for i, choice_text in enumerate(texts): db.session.add(Choice(question_id=q.id, text=choice_text, is_correct=(i==correct), position=i))
            db.session.commit(); flash('Questão dissertativa adicionada!' if question_type == 'essay' else 'Questão adicionada ao banco!', 'success')
            return redirect(url_for('question_detail', question_id=q.id))
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
    if q.question_type == 'essay':
        answer_text = request.form.get('answer_text', '').strip()
        if len(answer_text) < 1:
            flash('Escreva sua resposta antes de enviar.', 'error')
            return redirect(url_for('question_detail', question_id=q.id))
        db.session.add(EssayResponse(user_id=current_user.id, question_id=q.id, answer_text=answer_text))
        db.session.commit()
        return render_template('answer_result.html', q=q, choice=None, correct=None, essay_answer=answer_text, ai_available=not bool(q.expected_answer))
    try: choice_id = int(request.form.get('choice_id',''))
    except ValueError: abort(400)
    choice = Choice.query.filter_by(id=choice_id, question_id=q.id).first_or_404()
    has_answer_key = any(c.is_correct for c in q.choices)
    if has_answer_key:
        attempt = Attempt(user_id=current_user.id, question_id=q.id, choice_id=choice.id, is_correct=choice.is_correct, mode='study')
        db.session.add(attempt); db.session.commit()
    return render_template('answer_result.html', q=q, choice=choice, correct=(choice.is_correct if has_answer_key else None), essay_answer=None, ai_available=not has_answer_key)


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
        total = len(attempts); correct = sum(a.is_correct is True for a in attempts)
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
                val=request.form.get(f'q_{q.id}', '').strip()
                if q.question_type == 'essay':
                    if val:
                        answers[str(q.id)] = val
                        db.session.add(EssayResponse(user_id=current_user.id, question_id=q.id, answer_text=val))
                elif val.isdigit() and any(c.id==int(val) for c in q.choices):
                    answers[str(q.id)]=int(val)
        score=0
        for q in qs:
            if q.question_type == 'essay':
                continue
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
    graded_total=sum(1 for q in qs if q.question_type != 'essay')
    for q in qs:
        answer=answers.get(str(q.id))
        if q.question_type == 'essay':
            details.append({'q':q,'chosen':None,'answer_text':answer if isinstance(answer,str) else None,'correct':None,'ok':None,'manual':True})
        else:
            cid=answer if isinstance(answer,int) else None
            chosen=next((c for c in q.choices if c.id==cid),None); correct=next((c for c in q.choices if c.is_correct),None)
            details.append({'q':q,'chosen':chosen,'answer_text':None,'correct':correct,'ok':bool(chosen and chosen.is_correct),'manual':False})
    return render_template('exam_result.html', exam=exam, details=details, total=len(qs), graded_total=graded_total, pct=round((exam.score or 0)*100/graded_total,1) if graded_total else 0)

@app.route('/admin/questions/<int:question_id>/delete', methods=['POST'])
@login_required
def admin_delete_question(question_id):
    if not backup_admin_required(): abort(403)
    q = db.session.get(Question, question_id) or abort(404)
    Attempt.query.filter_by(question_id=q.id).delete(synchronize_session=False)
    EssayResponse.query.filter_by(question_id=q.id).delete(synchronize_session=False)
    db.session.delete(q)
    db.session.commit()
    flash(f'Questão #{question_id} excluída.', 'success')
    return redirect(url_for('questions'))

@app.route('/admin/database/reset', methods=['POST'])
@login_required
def admin_reset_database():
    if not backup_admin_required(): abort(403)
    confirmation = request.form.get('confirmation', '').strip()
    if confirmation != 'RESETAR':
        flash('Reset cancelado: digite RESETAR exatamente para confirmar.', 'error')
        return redirect(url_for('backups_page'))
    # Preserve user accounts and the configured admin login, but erase study content/progress.
    with db.engine.begin() as conn:
        for model in (EssayResponse, Attempt, ExamSession, Choice, Question, StudyMaterial, SubjectCode):
            conn.execute(model.__table__.delete())
    flash('Banco de estudos resetado. Contas de usuário foram preservadas; questões, materiais e progresso foram apagados.', 'success')
    return redirect(url_for('backups_page'))

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


# Safe additive migration for existing databases (does not delete or rewrite questions).
with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if 'question' in inspector.get_table_names():
            cols = {c['name'] for c in inspector.get_columns('question')}
            with db.engine.begin() as conn:
                if 'review_status' not in cols:
                    conn.execute(text("ALTER TABLE question ADD COLUMN review_status VARCHAR(30) NOT NULL DEFAULT 'Revisada'"))
                if 'question_type' not in cols:
                    conn.execute(text("ALTER TABLE question ADD COLUMN question_type VARCHAR(24) NOT NULL DEFAULT 'multiple_choice'"))
                if 'expected_answer' not in cols:
                    conn.execute(text('ALTER TABLE question ADD COLUMN expected_answer TEXT'))
                if 'ai_generated' not in cols:
                    conn.execute(text('ALTER TABLE question ADD COLUMN ai_generated BOOLEAN NOT NULL DEFAULT FALSE'))
    except Exception as migration_error:
        app.logger.warning("Question review-status migration will retry on next startup: %s", migration_error)
