import re
from bs4 import BeautifulSoup
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

print("Title:", soup.title.string if soup.title else "None")

headers = soup.find_all(['h1', 'h2', 'h3'])
print("\nHeaders:")
for h in headers[:20]:
    print(f"- {h.text.strip()}")

print("\nButtons / Actions:")
for b in soup.find_all('button')[:20]:
    print(f"- {b.text.strip()}")

print("\nScripts functions:")
scripts = soup.find_all('script')
for script in scripts:
    if script.string:
        funcs = re.findall(r'function\s+(\w+)\s*\(|class\s+(\w+)\s*\{|const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>', script.string)
        for f in funcs[:30]:
            name = next(filter(None, f))
            print(f"- {name}")
