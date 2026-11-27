/* One shared visual treatment for result lists across all web modules.
   No data, inputs, filters, permissions or existing table actions are changed. */
(() => {
  'use strict';
  const root = document.querySelector('.page-content');
  if (!root) return;
  const excluded = '.repeat-table, [data-plain-table], .editor-surface, .certificate-frame, .challan, .result-marks-table, .exam-preview-table, .date-sheet-table, #school-payroll-policy, #salary-attendance-deductions';
  const tones = {
    positive: new Set(['active','approved','present','paid','currently enrolled','enrolled','completed','success','successful','delivered','published','verified','converted']),
    warning: new Set(['pending','waiting','waiting approval','late','partial','partially paid','follow-up','pending review','draft','review required','processing','short leave','leave','paper leave']),
    negative: new Set(['absent','rejected','refused','unpaid','failed','overdue','suspended','expelled','struck off','duplicate record','cancelled','canceled']),
    neutral: new Set(['inactive','left','withdrawn','passed out','closed','voided','removed','off day','death leave','not marked','unmarked','disabled'])
  };
  const normalize = text => text.trim().toLowerCase().replace(/\s+/g, ' ');
  const tone = text => Object.keys(tones).find(key => tones[key].has(normalize(text)));
  const ownCells = row => Array.from(row.cells);
  const headingRow = table => {
    const candidate = table.tHead?.rows[0] || table.rows[0];
    return candidate && candidate.cells.length >= 2 && ownCells(candidate).every(cell => cell.tagName === 'TH') ? candidate : null;
  };
  const skipRow = row => row.matches('.report-print-signature,.finance-class,.finance-group,.group-total-row,.grand-total-row,.challan-family-total,.challan-total,[data-result-summary]') ||
    row.querySelector(':scope > .empty-state') || ownCells(row).some(cell => cell.colSpan > 1) && ownCells(row).length === 1;
  const selection = row => Array.from(row.querySelectorAll('input[type="checkbox"]')).some(input =>
    input.checked && !input.disabled && (input.closest('td') === row.cells[0] || /^(ids|employee_ids|student_ids|person_ids|selected_ids)$/.test(input.name) || input.matches('[data-monthly-pick]')));
  const nameColumn = text => /^(student|student name|employee|employee name|employee \/ teacher|teacher|teacher name|staff|staff name|name|employee info|student info|person|person name)$/.test(text);
  const statusColumn = text => /^(status|current status|payment status|approval status|attendance status|account status)$/.test(text);

  function enhance(table) {
    if (table.closest(excluded) || table.parentElement.closest('table')) return;
    const header = headingRow(table);
    if (!header) return;
    const columns = ownCells(header).map(cell => normalize(cell.textContent));
    const span = columns.length;
    const tableRows = () => Array.from(table.tBodies).flatMap(body => Array.from(body.rows));
    // Exclude form-only settings grids: no record-identifying text, just fields.
    const firstRows = tableRows().filter(row => row !== header && !skipRow(row));
    if (firstRows.length && firstRows.every(row => {
      const cells=ownCells(row).filter(cell => cell.tagName==='TD');
      return cells.length && cells.every(cell => cell.querySelector('input,select,textarea') && !cell.querySelector('a'));
    })) return;
    table.classList.add('sf-result-table');
    header.classList.add('sf-result-heading');
    const banner = document.createElement('div');
    banner.className = 'sf-results-banner no-print';
    banner.setAttribute('role','status');
    banner.setAttribute('aria-live','polite');
    const label = document.createElement('span');
    label.textContent = 'Records loaded';
    const count = document.createElement('span');
    count.className = 'sf-results-count';
    banner.append(label,count);
    const wrapper = table.parentElement;
    // Keep the count visible above the scroll area, within the owning section.
    if (wrapper.matches('.table,.scroll,.attendance-scroll,.payroll-preview-scroll,.monthly-roster-scroll') && !wrapper.matches('.form-card,.panel,.report-table-output')) wrapper.before(banner);
    else table.before(banner);
    let frame = 0;
    const refresh = () => {
      frame = 0;
      let visible = 0;
      for (const row of tableRows()) {
        if (row === header) continue;
        const cells = ownCells(row);
        const record = cells.length >= 2 && cells.some(cell => cell.tagName === 'TD') && !skipRow(row);
        row.classList.toggle('sf-result-row',record);
        row.classList.toggle('sf-result-selected',record && selection(row));
        const empty = !record && cells.length === 1 && cells[0].colSpan >= span &&
          /^(no |nothing |add |there are no)/i.test(cells[0].textContent.trim()) && !row.matches('.report-print-signature');
        row.classList.toggle('sf-result-empty',empty);
        if (!record) continue;
        if (!row.hidden && row.style.display !== 'none' && getComputedStyle(row).display !== 'none') visible++;
        if (cells.length === span && cells.every(cell => cell.colSpan === 1)) {
          cells.forEach((cell,index) => {
            if (nameColumn(columns[index])) cell.classList.add('sf-result-name');
            if (statusColumn(columns[index]) && !cell.querySelector('input,select,textarea,a,button,.status-pill') && !cell.hasAttribute('data-attendance-status')) {
              const value = tone(cell.textContent);
              cell.classList.toggle('sf-status-cell',Boolean(value));
              if (value) cell.dataset.sfTone=value; else delete cell.dataset.sfTone;
            }
          });
        }
        for (const badge of row.querySelectorAll('.status-pill')) {
          const value=tone(badge.textContent);
          if (value) badge.dataset.sfTone=value; else delete badge.dataset.sfTone;
        }
      }
      const title=visible ? 'Records loaded' : 'No matching records';
      const caption=visible+' '+(visible===1?'row':'rows')+' displayed';
      // Avoid repetitive announcements on unrelated form changes.
      if(label.textContent!==title) label.textContent=title;
      if(count.textContent!==caption) count.textContent=caption;
      banner.dataset.empty=String(!visible);
    };
    const schedule = () => { if(!frame) frame=requestAnimationFrame(refresh); };
    const form = table.closest('form');
    (form || table).addEventListener('change',schedule);
    (form || table).addEventListener('input',schedule);
    // Support live filters and asynchronously refreshed body rows, without
    // counting headers, report signatures, empty placeholders or footers.
    new MutationObserver(schedule).observe(table,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden','style']});
    refresh();
  }

  root.querySelectorAll('table').forEach(enhance);
})();
