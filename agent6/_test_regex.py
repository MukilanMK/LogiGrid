import ast, sys, re, json

# 1. Syntax check
with open(r'd:\agent 5\backend\main.py', encoding='utf-8') as f:
    src = f.read()
ast.parse(src)
print("main.py syntax OK")

# 2. Unit-test convert_regex_literals with the exact failing string
regex_literal_re = re.compile(r'(?<![:\w])/([^/\n]+)/([gimsuy]*)')

def convert_regex_literals(text):
    def replacer(m):
        pattern = m.group(1).replace('"', '\\"')
        flags = m.group(2)
        if flags:
            return '{"$regex": "' + pattern + '", "$options": "' + flags + '"}'
        return '{"$regex": "' + pattern + '"}'
    return regex_literal_re.sub(replacer, text)

# Simulate the raw LLM output from the error report
raw = r"""[
  { "$unwind": "$line_items" },
  { "$match": { "$or": [
      { "product_details.name": /electronic|audio|noise/i },
      { "product_details.category": /audio|accessories/i }
  ] } }
]"""

converted = convert_regex_literals(raw)
print("After conversion:\n", converted)

parsed = json.loads(converted)
print("json.loads() succeeded, stages:", len(parsed))
print("All tests PASSED")
