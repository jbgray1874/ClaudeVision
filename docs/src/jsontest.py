@'
lines = open('src/json_normaliser.py', encoding='utf-8').readlines()
out = []
i = 0
while i < len(lines):
    line = lines[i]
    if 'GRAPHIC", "ARTWORK", "POSTER", "PRINT INSERT")):' in line:
        out.append('    if any(k in _desc_upper or k in pn_u for k in ("GRAPHIC", "ARTWORK", "POSTER", "PRINT INSERT")):\n')
        out.append('        return "BOUGHT_IN"\n')
        out.append('    if "TICKET" in _desc_upper and "PLATE" not in _desc_upper and "HOLDER" not in _desc_upper:\n')
        out.append('        return "BOUGHT_IN"\n')
        i += 1
        while i < len(lines) and lines[i].strip() in ('return "BOUGHT_IN"', ''):
            if lines[i].strip() == '':
                break
            i += 1
        continue
    out.append(line)
    i += 1
open('src/json_normaliser.py', 'w', encoding='utf-8').writelines(out)
print('Done')
'@ | Out-File -Encoding utf8 src\fix_ticket.py

python src\fix_ticket.py
python -c "import ast; ast.parse(open('src/json_normaliser.py').read()); print('Syntax OK')"