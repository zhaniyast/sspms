"""
SSPMS backend — serves the trained model over HTTP.

Run from the project root:

    python server.py

then open http://127.0.0.1:8000/

Replaces `python -m http.server`: it serves the same webapp/ folder AND answers
prediction requests, so the What-if simulator queries the model live instead of
reading a precomputed grid.

Uses Flask if it is installed and falls back to the standard library otherwise,
so it runs on any machine in the team without `pip install`.

Endpoints
    GET  /                     the prototype (everything in webapp/)
    GET  /api/model            which model is loaded and how it scored
    GET  /predictions.json     the cohort: risk + top-3 factors per student
    POST /api/predict          live scoring; body: {"student_id": int,
                               "overrides": {"mean_score": 70, ...}}
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import joblib

ROOT = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.join(ROOT, 'webapp')
DATA = os.path.join(ROOT, 'data', 'processed', 'final_model_data.csv')

# The notebook saves two models. final_model.joblib is trained on every cohort,
# which is what you would deploy — but scoring the demo cohort with it means
# scoring data it was trained on, and the risks come out flattered. If the
# held-out model is there, prefer it: its numbers match the reported metrics.
MODEL_PATHS = [os.path.join(ROOT, 'models', 'holdout_model.joblib'),
               os.path.join(ROOT, 'models', 'final_model.joblib')]

ID_COLS = ['code_module', 'code_presentation', 'id_student']
SAMPLE_SIZE = 40
SEED = 42

FEATURE_LABELS = {
    'num_of_prev_attempts': 'previous attempts at this course',
    'studied_credits': 'credit load this term',
    'avg_weekly_clicks': 'average clicks per week',
    'total_clicks': 'total clicks in weeks 1-6',
    'avg_active_days': 'active days per week',
    'total_materials': 'distinct course materials opened',
    'silent_weeks': 'weeks with no activity at all',
    'clicks_last_2w': 'clicks in the last 2 weeks',
    'clicks_first_2w': 'clicks in the first 2 weeks',
    'click_trend': 'change in activity (last 2 weeks vs first 2)',
    'n_submitted': 'assignments submitted',
    'mean_score': 'average score so far',
    'min_score': 'lowest score so far',
    'points_earned': 'weighted points earned so far',
    'n_missed': 'assignments missed',
    'submitted_share': 'share of due assignments submitted',
}

FIRST = ['Aidana', 'Aruzhan', 'Dana', 'Madina', 'Nuray', 'Merey', 'Alina', 'Kamila',
         'Zarina', 'Asel', 'Dias', 'Alikhan', 'Nurlan', 'Timur', 'Arman', 'Yerlan',
         'Daniyar', 'Bekzat', 'Olzhas', 'Sanzhar']
LAST = ['Mukan', 'Ilyas', 'Sadyk', 'Abenov', 'Serik', 'Zhumabek', 'Kenzhe', 'Bolat',
        'Orazbek', 'Tasmagambet']


# ----------------------------------------------------------------- model state
class Service:
    def __init__(self):
        path = next((p for p in MODEL_PATHS if os.path.exists(p)), None)
        if path is None:
            sys.exit(f'No model found. Expected one of:\n  ' + '\n  '.join(MODEL_PATHS) +
                     '\nRun notebooks/03_modelling.ipynb first.')
        if not os.path.exists(DATA):
            sys.exit(f'No dataset at {DATA}. Run notebooks/01_data_pipeline_and_eda.ipynb first.')

        art = joblib.load(path)
        self.model = art['model']
        self.features = art['features']
        self.threshold = float(art['threshold'])
        self.source = os.path.basename(path)
        self.trained_on = art.get('trained_on', 'all cohorts')
        self.recall_mean = float(art.get('cv_recall_mean', 0.700))
        self.recall_sd = float(art.get('cv_recall_std', 0.077))
        self.prediction_week = int(art.get('prediction_week', 6))

        df = pd.read_csv(DATA)
        self.cohort = sorted((df.code_module + '-' + df.code_presentation).unique())[-1]
        mask = (df.code_module + '-' + df.code_presentation) == self.cohort
        self.df = df[mask].reset_index(drop=True)
        self.X = self.df[self.features].astype(float)
        self.medians = df[self.features].median()
        self.risk = self.model.predict_proba(self.X)[:, 1]

        rng = np.random.default_rng(SEED)
        self.sample = sorted(rng.choice(len(self.df), size=min(SAMPLE_SIZE, len(self.df)),
                                        replace=False).tolist())
        print(f'model   : {self.source} ({self.trained_on})')
        print(f'cohort  : {self.cohort}, {len(self.df)} students, '
              f'{int((self.risk >= self.threshold).sum())} above threshold {self.threshold:.3f}')

    # Per-feature contribution: re-score the student with one value replaced by
    # the population median and keep the difference. Exact, model-based, and it
    # needs no extra library — the same method the notebook uses for US8.
    def contributions(self, row: pd.DataFrame) -> np.ndarray:
        base = float(self.model.predict_proba(row)[:, 1][0])
        alts = []
        for f in self.features:
            a = row.copy()
            a[f] = self.medians[f]
            alts.append(a)
        others = self.model.predict_proba(pd.concat(alts, ignore_index=True))[:, 1]
        return base - others

    def factors(self, row: pd.DataFrame, top_n: int = 3):
        push = self.contributions(row)
        order = [j for j in np.argsort(-push) if push[j] > 0][:top_n]
        return [{'label': FEATURE_LABELS.get(self.features[j], self.features[j]),
                 'value': round(float(row.iloc[0, j]), 1),
                 'average': round(float(self.medians[self.features[j]]), 1),
                 'weight': round(float(push[j]), 3)} for j in order]

    def students(self):
        out = []
        for k, i in enumerate(self.sample):
            out.append({
                'id': int(self.df.at[i, 'id_student']),
                'name': f'{FIRST[k % len(FIRST)]} {LAST[k % len(LAST)]}',
                'course': f"{self.df.at[i, 'code_module']} {self.df.at[i, 'code_presentation']}",
                'risk': round(float(self.risk[i]), 3),
                'flag': bool(self.risk[i] >= self.threshold),
                'actual_at_risk': int(self.df.at[i, 'at_risk']),
                'factors': self.factors(self.X.iloc[[i]]),
            })
        out.sort(key=lambda s: -s['risk'])
        return {
            'model': 'RandomForest (tuned)',
            'threshold': round(self.threshold, 3),
            'recall_mean': self.recall_mean,
            'recall_sd': self.recall_sd,
            'prediction_week': self.prediction_week,
            'cohort': self.cohort,
            'served_by': 'server.py (live)',
            'names': 'synthetic placeholders; student ids are the real OULAD ids',
            'students': out,
        }

    def predict(self, payload: dict):
        sid = payload.get('student_id')
        hits = self.df.index[self.df.id_student == sid] if sid is not None else []
        i = int(hits[0]) if len(hits) else int(self.sample[0])
        row = self.X.iloc[[i]].copy()

        # Apply only the features the caller actually sent, and keep the
        # dependent columns consistent so the row stays a plausible student.
        ov = payload.get('overrides') or {}
        for f, v in ov.items():
            if f in self.features:
                row[f] = float(v)
        if 'mean_score' in ov and 'min_score' not in ov:
            row['min_score'] = float(ov['mean_score'])
        if 'avg_weekly_clicks' in ov:
            c = float(ov['avg_weekly_clicks'])
            row['total_clicks'] = c * 6
            row['clicks_last_2w'] = c * 2
        if 'submitted_share' in ov and 'n_submitted' not in ov:
            sh = float(ov['submitted_share'])
            row['n_submitted'] = round(sh * 2)
            row['n_missed'] = 2 - round(sh * 2)

        risk = float(self.model.predict_proba(row)[:, 1][0])
        return {'student_id': int(self.df.at[i, 'id_student']),
                'risk': round(risk, 3),
                'flag': bool(risk >= self.threshold),
                'threshold': round(self.threshold, 3),
                'factors': self.factors(row)}

    def meta(self):
        return {'model_file': self.source, 'trained_on': self.trained_on,
                'features': self.features, 'threshold': round(self.threshold, 3),
                'recall_mean': self.recall_mean, 'recall_sd': self.recall_sd,
                'prediction_week': self.prediction_week, 'cohort': self.cohort,
                'students_in_cohort': len(self.df)}


SVC = Service()
CACHED = SVC.students()          # scoring 40 students takes a moment; do it once


# ------------------------------------------------------------------- transport
def run_flask():
    from flask import Flask, request, jsonify, send_from_directory
    app = Flask(__name__, static_folder=None)

    @app.get('/api/model')
    def meta():
        return jsonify(SVC.meta())

    @app.get('/predictions.json')
    def students():
        return jsonify(CACHED)

    @app.post('/api/predict')
    def predict():
        return jsonify(SVC.predict(request.get_json(silent=True) or {}))

    @app.get('/')
    def index():
        return send_from_directory(WEBAPP, 'index.html')

    @app.get('/<path:path>')
    def static_file(path):
        return send_from_directory(WEBAPP, path)

    print('backend : Flask on http://127.0.0.1:8000/')
    app.run(port=8000, debug=False)


def run_stdlib():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import posixpath, urllib.parse, mimetypes

    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == '/api/model':
                return self._json(SVC.meta())
            if path == '/predictions.json':
                return self._json(CACHED)
            rel = posixpath.normpath(path).lstrip('/') or 'index.html'
            full = os.path.join(WEBAPP, *rel.split('/'))
            # keep the served file inside webapp/
            if not os.path.abspath(full).startswith(WEBAPP) or not os.path.isfile(full):
                return self._json({'error': 'not found'}, 404)
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            data = open(full, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != '/api/predict':
                return self._json({'error': 'not found'}, 404)
            n = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(n) or b'{}')
            self._json(SVC.predict(payload))

        def log_message(self, *a):
            pass

    print('backend : standard library on http://127.0.0.1:8000/  (pip install flask for Flask)')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()


if __name__ == '__main__':
    try:
        import flask  # noqa: F401
        run_flask()
    except ImportError:
        run_stdlib()
