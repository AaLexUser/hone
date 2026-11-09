"""Builds index.html from body.html, body.css, fonts.css and diagram.svg.

The bar charts come from the paper's Table I.
"""
import os

D = os.path.dirname(os.path.abspath(__file__))
read = lambda f: open(os.path.join(D, f)).read()

TABLE_I = {  # task success %, GPT-5.4-mini target model
    'OfficeQA': {'Hone': 59.7, 'Pi agent': 56.7, 'Codex CLI': 54.9, 'SkillOpt': 50.6, 'EvoSkill': 41.5, 'Trace2Skill': 20.9},
    'SpreadsheetBench': {'Hone': 82.3, 'Pi agent': 71.0, 'Codex CLI': 72.3, 'SkillOpt': 80.4, 'EvoSkill': 65.3, 'Trace2Skill': 40.7},
}
ORDER = [('Hone', 'hone'), ('Pi agent', 'base'), ('Codex CLI', ''), ('SkillOpt', ''), ('EvoSkill', ''), ('Trace2Skill', '')]


def chart(bench):
    r = TABLE_I[bench]
    bars = '\n'.join(
        f'      <div class="bar {k}"><span class="l">{n}</span><span class="tr"><span class="b" style="width:{r[n]}%"></span>'
        f'<span class="v" style="left:{r[n]}%">{r[n]:.1f}</span></span></div>' for n, k in ORDER)
    return f'    <div class="panel chart">\n      <p class="bench">{bench}, task success %</p>\n{bars}\n    </div>'


CHARTS = chart('OfficeQA') + '\n' + chart('SpreadsheetBench')

html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>Hone · ICDM 2026 demo poster</title>\n<style>\n'
        + read('fonts.css') + read('body.css') + '</style>\n</head>\n<body>\n'
        + read('body.html').replace('@@CHARTS@@', CHARTS).replace('@@SVG@@', read('diagram.svg'))
        + '\n</body>\n</html>\n')
open(os.path.join(D, '..', 'index.html'), 'w').write(html)
print('built index.html')
