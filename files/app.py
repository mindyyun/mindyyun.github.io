from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
import json
import os
import csv
import io
import random
import glob
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'psych_experiment_secret_key_2024'

DATA_FILE = 'data/results.json'
COUNTER_FILE = 'data/counter.json'
IMAGES_DIR = 'static/images'

ADMIN_USER = 'bestiewestie'
ADMIN_PASS = 'whyamicodinginpsych!'

ROUND_DURATIONS = [1520, 1020, 520, 20]  # ms per image
PHOTOS_PER_ROUND = 10
BLANK_DURATION = 500  # ms neutral blank between photos

os.makedirs('data', exist_ok=True)

def get_next_participant_id():
    if not os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, 'w') as f:
            json.dump({'counter': 0}, f)
        return 0
    with open(COUNTER_FILE, 'r') as f:
        data = json.load(f)
    pid = data['counter']
    data['counter'] += 1
    with open(COUNTER_FILE, 'w') as f:
        json.dump(data, f)
    return pid

def get_all_images():
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp']
    images = []
    for ext in extensions:
        images.extend(glob.glob(os.path.join(IMAGES_DIR, ext)))
    images = [os.path.basename(f) for f in images]
    return images

def build_experiment(all_images):
    """
    Build 4 rounds. Each round: 10 study images (mix of color/BW) shown at round duration,
    then 1 test image (old or new) rated on Likert scale.
    Returns the full experiment structure.
    """
    if len(all_images) < 40 + 4:
        # If fewer images, reuse with caution
        pool = all_images[:]
    else:
        pool = all_images[:]

    random.shuffle(pool)

    rounds = []
    used_study = []
    durations = ROUND_DURATIONS[:]
    random.shuffle(durations)  # randomize which round gets which duration

    for r in range(4):
        # Pick 10 study images
        study_images = []
        for i in range(PHOTOS_PER_ROUND):
            if not pool:
                pool = all_images[:]
                random.shuffle(pool)
            img = pool.pop(0)
            study_images.append(img)
            used_study.append(img)

        # Each study image: randomly color or BW
        study_sequence = []
        for img in study_images:
            is_color = random.choice([True, False])
            study_sequence.append({'image': img, 'color': is_color})

        # Test image: 50% chance old (from this round's study), 50% new
        is_old = random.choice([True, False])
        if is_old and study_images:
            test_image = random.choice(study_images)
        else:
            # Pick a new image not in used_study
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

def save_result(participant_id, round_results):
    results = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            results = json.load(f)
    results.append({
        'participant_id': participant_id,
        'timestamp': datetime.now().isoformat(),
        'rounds': round_results
    })
    with open(DATA_FILE, 'w') as f:
        json.dump(results, f, indent=2)

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
        return jsonify({'error': 'No images found. Please add images to static/images/'}), 400

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
        'round': data.get('round'),
        'duration_ms': data.get('duration_ms'),
        'test_image': data.get('test_image'),
        'test_is_old': data.get('test_is_old'),
        'response': data.get('response'),  # 1-5 Likert
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
    results = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            results = json.load(f)
    return render_template('admin_dashboard.html', results=results)

@app.route('/admin/download')
@admin_required
def admin_download():
    results = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            results = json.load(f)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'participant_id', 'timestamp', 'round', 'duration_ms',
        'test_image', 'test_is_old', 'likert_response',
        'study_images', 'color_sequence'
    ])

    for r in results:
        pid = r['participant_id']
        ts = r['timestamp']
        for rnd in r.get('rounds', []):
            study_seq = rnd.get('study_sequence', [])
            study_imgs = '|'.join([s['image'] for s in study_seq])
            color_seq = '|'.join(['color' if s['color'] else 'bw' for s in study_seq])
            writer.writerow([
                pid, ts,
                rnd.get('round'),
                rnd.get('duration_ms'),
                rnd.get('test_image'),
                rnd.get('test_is_old'),
                rnd.get('response'),
                study_imgs,
                color_seq
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

if __name__ == '__main__':
    app.run(debug=True)
