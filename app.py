from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
import json
import os
import csv
import io
import random
import glob
from datetime import datetime
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'psych_experiment_secret_key_2024')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, 'static', 'images')

ADMIN_USER = 'bestiewestie'
ADMIN_PASS = 'whyamicodinginpsych!'

ROUND_DURATIONS = [1520, 1020, 520, 20]  # fixed order: longest to shortest
PHOTOS_PER_ROUND = 10
BLANK_DURATION = 500  # ms neutral blank between photos

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    """Open a new database connection using the DATABASE_URL environment variable."""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    # Render provides postgres:// but psycopg2 needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)

def init_db():
    """Create tables if they don't exist yet."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS participants (
                    id          SERIAL PRIMARY KEY,
                    pid         INTEGER UNIQUE NOT NULL,
                    timestamp   TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    id              SERIAL PRIMARY KEY,
                    pid             INTEGER NOT NULL REFERENCES participants(pid),
                    round           INTEGER,
                    duration_ms     INTEGER,
                    test_image      TEXT,
                    test_is_old     BOOLEAN,
                    likert_response INTEGER,
                    study_sequence  JSONB,
                    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pid_counter (
                    id      INTEGER PRIMARY KEY DEFAULT 1,
                    counter INTEGER NOT NULL DEFAULT 0,
                    CHECK (id = 1)
                );
            """)
            # Ensure the single counter row exists
            cur.execute("""
                INSERT INTO pid_counter (id, counter)
                VALUES (1, 0)
                ON CONFLICT (id) DO NOTHING;
            """)
        conn.commit()
    finally:
        conn.close()

def get_next_participant_id():
    """Atomically increment and return the next participant ID."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pid_counter SET counter = counter + 1
                WHERE id = 1
                RETURNING counter - 1 AS pid;
            """)
            row = cur.fetchone()
        conn.commit()
        return row['pid']
    finally:
        conn.close()

def save_result(participant_id, round_results):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO participants (pid, timestamp) VALUES (%s, %s) ON CONFLICT (pid) DO NOTHING;",
                (participant_id, datetime.now())
            )
            for rnd in round_results:
                cur.execute("""
                    INSERT INTO responses
                        (pid, round, duration_ms, test_image, test_is_old, likert_response, study_sequence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (
                    participant_id,
                    rnd.get('round'),
                    rnd.get('duration_ms'),
                    rnd.get('test_image'),
                    rnd.get('test_is_old'),
                    rnd.get('response'),
                    json.dumps(rnd.get('study_sequence', []))
                ))
        conn.commit()
    finally:
        conn.close()

def load_all_results():
    """Return all results grouped by participant, same shape as the old JSON format."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pid, timestamp FROM participants ORDER BY pid;")
            participants = cur.fetchall()

            results = []
            for p in participants:
                cur.execute("""
                    SELECT round, duration_ms, test_image, test_is_old,
                           likert_response AS response, study_sequence
                    FROM responses WHERE pid = %s ORDER BY round;
                """, (p['pid'],))
                rounds_raw = cur.fetchall()
                rounds = []
                for r in rounds_raw:
                    seq = r['study_sequence']
                    if isinstance(seq, str):
                        seq = json.loads(seq)
                    rounds.append({
                        'round': r['round'],
                        'duration_ms': r['duration_ms'],
                        'test_image': r['test_image'],
                        'test_is_old': r['test_is_old'],
                        'response': r['response'],
                        'study_sequence': seq or []
                    })
                results.append({
                    'participant_id': p['pid'],
                    'timestamp': p['timestamp'].isoformat() if p['timestamp'] else '',
                    'rounds': rounds
                })
        return results
    finally:
        conn.close()

# ─── Experiment logic ──────────────────────────────────────────────────────────

def get_all_images():
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp']
    images = []
    for ext in extensions:
        images.extend(glob.glob(os.path.join(IMAGES_DIR, ext)))
    return [os.path.basename(f) for f in images]

def build_experiment(all_images):
    pool = all_images[:]
    random.shuffle(pool)

    rounds = []
    used_study = []
    durations = ROUND_DURATIONS[:]  # fixed order: 1520, 1020, 520, 20 ms

    for r in range(4):
        study_images = []
        for i in range(PHOTOS_PER_ROUND):
            if not pool:
                pool = all_images[:]
                random.shuffle(pool)
            img = pool.pop(0)
            study_images.append(img)
            used_study.append(img)

        study_sequence = [
            {'image': img, 'color': random.choice([True, False])}
            for img in study_images
        ]

        is_old = random.choice([True, False])
        if is_old and study_images:
            test_image = random.choice(study_images)
        else:
            remaining = [img for img in all_images if img not in used_study]
            if remaining:
                test_image = random.choice(remaining)
                is_old = False
            else:
                test_image = random.choice(study_images)
                is_old = True

        rounds.append({
            'round_number': r + 1,
            'duration_ms': durations[r],
            'study_sequence': study_sequence,
            'test_image': test_image,
            'test_is_old': is_old,
            'blank_duration_ms': BLANK_DURATION
        })

    return rounds

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    all_images = get_all_images()
    if not all_images:
        return jsonify({'error': 'No images found in static/images/'}), 400

    pid = get_next_participant_id()
    experiment = build_experiment(all_images)

    session['participant_id'] = pid
    session['experiment'] = experiment
    session['responses'] = []

    return jsonify({'participant_id': pid, 'experiment': experiment})

@app.route('/submit_response', methods=['POST'])
def submit_response():
    data = request.json
    if 'participant_id' not in session:
        return jsonify({'error': 'No active session'}), 400

    responses = session.get('responses', [])
    responses.append({
        'round':        data.get('round'),
        'duration_ms':  data.get('duration_ms'),
        'test_image':   data.get('test_image'),
        'test_is_old':  data.get('test_is_old'),
        'response':     data.get('response'),
        'study_sequence': data.get('study_sequence')
    })
    session['responses'] = responses
    return jsonify({'ok': True})

@app.route('/finish', methods=['POST'])
def finish():
    pid = session.get('participant_id')
    responses = session.get('responses', [])
    if pid is None:
        return jsonify({'error': 'No active session'}), 400
    save_result(pid, responses)
    session.clear()
    return jsonify({'ok': True})

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='Invalid credentials')
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    results = load_all_results()

    total_responses = 0
    total_correct = 0
    enriched = []
    for r in results:
        p_correct = 0
        p_total = 0
        enriched_rounds = []
        for rnd in r.get('rounds', []):
            p_total += 1
            total_responses += 1
            resp = rnd.get('response')
            is_old = rnd.get('test_is_old', False)
            correct = (is_old and resp in [1, 2]) or (not is_old and resp in [4, 5])
            if correct:
                p_correct += 1
                total_correct += 1
            study_seq = rnd.get('study_sequence', [])
            color_tags = ','.join(['C' if s.get('color') else 'BW' for s in study_seq])
            enriched_rounds.append({**rnd, 'correct': correct, 'color_tags': color_tags})
        enriched.append({**r, 'rounds': enriched_rounds,
                         'p_correct': p_correct, 'p_total': p_total})

    accuracy_pct = round(total_correct / total_responses * 100, 1) if total_responses > 0 else None
    return render_template('admin_dashboard.html',
        results=enriched,
        total_responses=total_responses,
        total_correct=total_correct,
        accuracy_pct=accuracy_pct,
        participant_count=len(results))

@app.route('/admin/download')
@admin_required
def admin_download():
    results = load_all_results()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'participant_id', 'timestamp', 'round', 'duration_ms',
        'test_image', 'test_is_old', 'likert_response',
        'study_images', 'color_sequence'
    ])
    for r in results:
        for rnd in r.get('rounds', []):
            study_seq = rnd.get('study_sequence', [])
            writer.writerow([
                r['participant_id'],
                r['timestamp'],
                rnd.get('round'),
                rnd.get('duration_ms'),
                rnd.get('test_image'),
                rnd.get('test_is_old'),
                rnd.get('response'),
                '|'.join(s['image'] for s in study_seq),
                '|'.join('color' if s['color'] else 'bw' for s in study_seq)
            ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=experiment_results.csv'}
    )

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# ─── Startup ──────────────────────────────────────────────────────────────────

# Initialise DB tables on first boot (safe to call repeatedly)
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"[WARNING] Could not initialise database: {e}")
        print("Set the DATABASE_URL environment variable to enable persistent storage.")

if __name__ == '__main__':
    from waitress import serve
    print('Starting server at http://0.0.0.0:5000')
    serve(app, host='0.0.0.0', port=5000, threads=16)
