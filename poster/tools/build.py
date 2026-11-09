"""Builds index.html from body.html, body.css, fonts.css and diagram.svg.

The results strip comes from the paper's Table I. The session x finding grid
comes from the scripted demo seed (hone/scripts/dev/seed_runs.py): sessions
t01..t13 in review batches (t01-t04), (t05-t08), (t09-t10), (t11-t13); a dot
is a session the finding cites, a ring a session whose user comment it cites.
"""
import os

D = os.path.dirname(os.path.abspath(__file__))
read = lambda f: open(os.path.join(D, f)).read()

TABLE_I = {  # task success %, GPT-5.4-mini target model
    'OfficeQA': {'Hone': 59.7, 'Pi agent': 56.7, 'Codex CLI': 54.9, 'SkillOpt': 50.6, 'EvoSkill': 41.5, 'Trace2Skill': 20.9},
    'SpreadsheetBench': {'Hone': 82.3, 'Pi agent': 71.0, 'Codex CLI': 72.3, 'SkillOpt': 80.4, 'EvoSkill': 65.3, 'Trace2Skill': 40.7},
}
ORDER = [('Hone', 'hone'), ('Pi agent', 'agent'), ('Codex CLI', 'agent'), ('SkillOpt', 'opt'), ('EvoSkill', 'opt'), ('Trace2Skill', 'opt')]


def half(bench, extra=''):
    r = TABLE_I[bench]
    gain = r['Hone'] - r['Pi agent']
    bars = '\n        '.join(
        f'<div class="br {k}"><span class="l">{n}</span><span class="tr"><span class="b" style="width:{r[n]}%"></span>'
        f'<span class="v" style="left:{r[n]}%">{r[n]:.1f}</span></span></div>' for n, k in ORDER)
    return f'''    <div class="half">
      <div class="hl"><p class="lab">{bench}</p><div class="v">+{gain:.1f}<small>pts</small></div>{extra}</div>
      <div class="mini">
        {bars}
      </div>
    </div>'''


HERO = f'''<section class="hero">
  <p class="top">Highest task success of six systems on both benchmarks. <span>Gain over the same Pi agent without Hone:</span></p>
  <div class="halves">
{half('OfficeQA')}
{half('SpreadsheetBench', '<p class="s2">+1.9 over SkillOpt</p>')}
  </div>
  <p class="cap"><b>Table I.</b> Task success, %, GPT-5.4-mini target model. <i class="sw hone"></i>Hone <i class="sw agent"></i>unoptimized agent <i class="sw opt"></i>skill optimizer (re-runs tasks with a verifier). The Pi agent is Hone's starting configuration; only AGENTS.md differs.</p>
  <p class="cap"><b>Setup.</b> Hone saw only traces and per-task feedback (“Expected … Got …”); no task re-run to score an edit. OfficeQA: 200 tasks, 5 batches of 40; final file scored once.</p>
</section>'''

BATCHES = [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10), (11, 12, 13)]
# (finding, cited sessions, commented sessions, recurrence in its batch, outcome kind, outcome text)
ROWS = [
    ('Dates written month-first', {1, 2, 3, 4}, {1}, '4/4', 'ok', 'became a rule'),
    ('Manager copied from an old letter', {4}, {4}, '1/4', 'ok', 'became a rule'),
    ('“Family name first”, for one candidate', {6}, {6}, '1/4', 'no', 'refused: one-off'),
    ('£0 and 0-share lines left in', {11, 12}, {11, 12}, '2/3', 'ok', 'became a rule'),
]


def cells(hit, ring):
    out = []
    for b in BATCHES:
        out.append('<span class="bt">' + ''.join(
            f'<i class="c{" on" if s in hit else ""}{" ring" if s in ring else ""}"></i>' for s in b) + '</span>')
    return ''.join(out)


HEAD = ''.join('<span class="bt">' + ''.join(f'<i class="c n">{s}</i>' for s in b) + '</span>' for b in BATCHES)
GRID = '<div class="grid">\n' \
    f'        <p class="gth">Finding · demo session</p><div class="gc gth">{HEAD}</div><p class="gth">Outcome</p>\n' + '\n'.join(
        f'        <p class="gf">{f}</p><div class="gc">{cells(h, r)}</div><p class="go {k}">{"✓" if k == "ok" else "×"} {o}</p>'
        for f, h, r, n, k, o in ROWS) + '\n      </div>\n      <p class="gl"><b>Demo scenario (scripted), illustrative.</b> <i class="c on"></i> cited session <i class="c on ring"></i> the user commented. No support threshold: the manager rule rests on one session.</p>'

html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>Hone · ICDM 2026 demo poster</title>\n<style>\n'
        + read('fonts.css') + read('body.css') + '</style>\n</head>\n<body>\n'
        + read('body.html').replace('@@HERO@@', HERO).replace('@@SVG@@', read('diagram.svg')).replace('@@GRID@@', GRID)
        + '\n</body>\n</html>\n')
open(os.path.join(D, '..', 'index.html'), 'w').write(html)
print('built index.html')
