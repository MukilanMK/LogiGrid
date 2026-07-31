"""
Rewrite the navigation of dashboard/app.py:
- Remove System Control Centre block (lines 149-210, was elif active_page PAGES[1])
- Remove About page block
- Replace all "elif active_page == PAGES[N]:" with "with _tab_X:"
- Replace "elif active_page == PAGES[0]:" (Procurement Pipeline) with "with _tab_procurement:"
"""
import sys

src = open('dashboard/app.py', encoding='utf-8').read()
lines = src.splitlines(keepends=True)

# ── Step 1: Remove System Control Centre block (lines 149-210 inclusive) ──────
# Line 149 starts with "    st.title(\"🎛️ System Control Centre\")"
# Line 210 ends with "    st.info(\"No log entries yet.\")\n"
# We keep lines 0-147 (index 0..147) and skip 148..209, keep from 210 onward
# BUT we must also remove the preceding "with _tab_procurement:\n" line that
# currently wraps it — line 148 is "with _tab_procurement:" which should stay
# but should contain the procurement content, not the system control content.

# Find the exact line indices
def find_line(text, start=0):
    for i, l in enumerate(lines):
        if i >= start and text in l:
            return i
    return -1

sys_ctrl_start = find_line('st.title("🎛️ System Control Centre")')
no_log_line    = find_line('st.info("No log entries yet.")')
invoice_page   = find_line('# PAGE: INVOICE AUDITOR')
vendor_page    = find_line('# PAGE: VENDOR QUALITY')
bi_page        = find_line('# PAGE: BI ANALYTICS')
about_page     = find_line('# PAGE: ABOUT')
procurement_elif = find_line('elif active_page == PAGES[0]:')

print(f"System Control start: {sys_ctrl_start+1}")
print(f"No log line:          {no_log_line+1}")
print(f"Invoice page:         {invoice_page+1}")
print(f"Vendor page:          {vendor_page+1}")
print(f"BI page:              {bi_page+1}")
print(f"About page:           {about_page+1}")
print(f"Procurement elif:     {procurement_elif+1}")

# Build the new file:
# Keep: lines 0..(sys_ctrl_start-1)   [everything before system control content]
# Skip: lines sys_ctrl_start..no_log_line  [system control body + "No log entries yet."]
# Keep: lines (no_log_line+1)..(about_page-1)  [invoice + vendor + bi pages]
# Skip: lines about_page..end          [about page and everything after it including
#                                       the old elif active_page == PAGES[0]]
# The procurement content follows the "with _tab_procurement:" we already have at line ~148

new_lines = []

# Before system control block (keep)
new_lines.extend(lines[:sys_ctrl_start])

# After "No log entries yet." — convert page delimiters
i = no_log_line + 1
total = len(lines)

# Mapping: old PAGES index -> new tab variable
tab_map = {
    'PAGES[2]': 'with _tab_invoice:',
    'PAGES[3]': 'with _tab_vendor:',
    'PAGES[4]': 'with _tab_bi:',
    'PAGES[0]': 'with _tab_procurement:',
}

in_about = False
while i < total:
    line = lines[i]

    # Detect start of About page — skip everything from here to procurement elif
    if '# PAGE: ABOUT' in line:
        in_about = True

    # Detect procurement elif — stop skipping, convert to with block
    if 'elif active_page == PAGES[0]:' in line:
        in_about = False
        new_lines.append('with _tab_procurement:\n')
        i += 1
        continue

    if in_about:
        i += 1
        continue

    # Replace elif active_page page headers with with blocks
    replaced = False
    for old, new in tab_map.items():
        if f'elif active_page == {old}:' in line:
            # Get the leading whitespace (should be none for top-level elif)
            new_lines.append(f'{new}\n')
            replaced = True
            break

    if not replaced:
        # Remove "# PAGE: ..." comment lines (they're now redundant with tab labels)
        if line.strip().startswith('# PAGE:') and ('# PAGE: VENDOR' in line or
            '# PAGE: INVOICE' in line or '# PAGE: BI ANALY' in line or
            '# PAGE: PROCUREMENT' in line):
            i += 1
            continue
        new_lines.append(line)

    i += 1

out = ''.join(new_lines)
open('dashboard/app.py', 'w', encoding='utf-8').write(out)
print(f'\nDone. New line count: {len(new_lines)}')
