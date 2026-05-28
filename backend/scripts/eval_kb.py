"""
KB Evaluation — 50 Q&A against agentic_search pipeline (standalone, no HTTP/server deps).
"""

import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workflow.kb_agent import agentic_search
from app.modules.kb_module import get_kb

# ── Parse Q&A ───────────────────────────────────────────────────────────────────

def parse_qa(path):
    content = open(path).read()
    pairs = []
    for block in re.split(r'\n---\n', content):
        m = re.search(r'## Q(\d+): (.+?)\n\n\*\*Q: (.+?)\*\*\n\nA: (.+)', block, re.DOTALL)
        if m:
            pairs.append({
                'num': int(m.group(1)),
                'topic': m.group(2).strip(),
                'question': m.group(3).strip(),
                'answer': m.group(4).strip(),
            })
    return pairs

def key_facts(answer):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', answer)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    facts = []
    for p in [
        r'[A-Z]{2,}[-/][A-Z0-9-]+',       # report IDs: YH-2840-S, MAT-2025-0715
        r'\d{4}[-/]\d{4}[-/]\d{4}',       # dates
        r'[\d\,\.]+(?:MPa|mm|円|pcs|個)',  # numbers with units
        r'\d+\.\d+%',                      # percentages: 75.4%, 0.02%, 1.8%
        r'(?:AQL|Cpk|OEE|Cpk)\s*\d+\.?\d*', # named metrics with values: AQL 1.0, Cpk 1.33
    ]:
        for m in re.finditer(p, text, re.IGNORECASE):
            v = m.group().strip()
            if len(v) >= 3:
                facts.append(v)
    return facts[:6]

def check(content, answer):
    facts = key_facts(answer)
    if not facts:
        return True, 100.0
    cl = content.lower()
    matched = [f for f in facts if f.lower() in cl]
    cov = len(matched) / len(facts)
    return cov >= 0.5, cov

# ── Run ─────────────────────────────────────────────────────────────────────────

qa_path = '/Users/jinyonghao/Desktop/factory-test-docs/QA_问答对_50组.md'
pairs = parse_qa(qa_path)

kb = get_kb()
print(f"KB entries: {len(kb._entries)}")
print(f"Q&A pairs: {len(pairs)}\n")

results = []
for p in pairs:
    try:
        sr = agentic_search(p['question'], top_k=5)
    except Exception as e:
        results.append({**p, 'status': 'ERROR', 'error': str(e), 'doc': None, 'cov': 0})
        continue
    doc = sr[0]['content'] if sr else ''
    passed, cov = check(doc, p['answer'])
    results.append({**p, 'status': 'PASS' if passed else 'FAIL',
                    'doc': sr[0]['title'] if sr else None, 'cov': cov})

total = len(results)
passed = sum(1 for r in results if r['status'] == 'PASS')
errors = sum(1 for r in results if r['status'] == 'ERROR')
acc = passed / max(total - errors, 1) * 100

print(f"=== Results ===")
print(f"Total:   {total}")
print(f"Passed:  {passed}")
print(f"Failed:  {total - passed - errors}")
print(f"Errors:  {errors}")
print(f"Accuracy: {acc:.1f}% ({passed}/{total - errors})\n")

failures = [r for r in results if r['status'] == 'FAIL']
if failures:
    print(f"=== Failures ({len(failures)}) ===")
    for r in failures[:15]:
        print(f"  Q{r['num']:02d} [{r['topic']}]")
        print(f"    Q: {r['question'][:70]}")
        print(f"    → returned: {r.get('doc', 'NONE')}")
        print(f"    → coverage: {r.get('cov', 0):.0%}")
        print()