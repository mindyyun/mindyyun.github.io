# Visual Memory & Food Imagery — Psychology Experiment

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Add your images
Place all food images (JPG, PNG, GIF, or WEBP) into:
```
static/images/
```
You need up to 120 images. The experiment will use a random subset each run.

### 3. Run the server
```bash
python app.py
```
Then open http://localhost:5000 in a browser.

---

## Participant Flow

1. Participant opens http://localhost:5000
2. Reads brief info and clicks **Begin Study**
3. Assigned a unique ID (starting at 0, incrementing)
4. Completes **4 rounds**, each with:
   - 10 study images shown (mix of color and B&W) at the round's exposure duration
   - A 500ms neutral blank screen between each image
   - At the end of the round, one test image (old or new)
   - A 5-point Likert rating: Definitely Old → Definitely New
5. After all 4 rounds: "You may close this tab" message

**Round durations (randomized order per participant):**
- 1520 ms
- 1020 ms
- 520 ms
- 20 ms

Participants **do not see their results**.

---

## Admin Portal

URL: http://localhost:5000/admin

- **Username:** bestiewestie
- **Password:** whyamicodinginpsych!

Features:
- Summary stats (total participants, responses, recognition accuracy)
- Per-participant expandable tables showing all round details
- **Download CSV** button — exports all data

### CSV columns:
| Column | Description |
|---|---|
| participant_id | Unique integer ID starting at 0 |
| timestamp | ISO datetime of experiment completion |
| round | Round number (1–4) |
| duration_ms | Exposure duration for that round |
| test_image | Filename of the test image shown |
| test_is_old | True if image appeared in study phase |
| likert_response | Participant response (1=Definitely Old, 5=Definitely New) |
| study_images | Pipe-separated list of study image filenames |
| color_sequence | Pipe-separated list: 'color' or 'bw' for each study image |

---

## Experiment Design (replicating Spence et al.)

**Independent variables:**
- Color vs. B&W (within-image, randomly assigned per study trial)
- Exposure duration (between-round: 20ms, 520ms, 1020ms, 1520ms)

**Dependent variable:**
- Recognition memory rating (1–5 Likert)

**Accuracy scoring:**
- Correct = "Definitely Old" or "Probably Old" (1 or 2) for an old image
- Correct = "Probably New" or "Definitely New" (4 or 5) for a new image
