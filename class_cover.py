"""Dated substitute assignments based on saved timetables and staff attendance."""
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from sqlalchemy import select

from school_clock import school_today
from workspace_actor import csrf, scopes

COVER = 'teacher-class-cover'
UNAVAILABLE = {'Absent', 'Leave', 'Full Day Leave', 'Death Leave', 'Paper Leave', 'Off Day'}


def configure_class_cover(app, db, Employee):
    bp = Blueprint('class_cover', __name__, url_prefix='/workspace/class-cover')
    models = app.extensions['ops_models']
    Workflow, Daily, Audit = (models[key] for key in ('workflow', 'daily', 'audit'))

    def absence_conditions(table, day):
        return (table.c.kind == 'staff', table.c.day == day, table.c.status.in_(UNAVAILABLE))

    def leave_conditions(table, day):
        key = day.isoformat()
        return (table.c.kind == 'leave-approvals', table.c.status == 'Approved',
                table.c.data['from_date'].as_string() <= key, table.c.data['to_date'].as_string() >= key)

    def has_unavailability(day):
        attendance, workflows = Daily.__table__, Workflow.__table__
        return (select(attendance.c.id).where(*absence_conditions(attendance, day)).exists()
                | select(workflows.c.id).where(*leave_conditions(workflows, day)).exists())

    def cover_records(day):
        return Workflow.query.filter_by(kind=COVER, status='Active').filter(
            Workflow.data['day'].as_string() == day.isoformat())

    def matches_period(record, period):
        return all(record.data.get(key) == period[key] for key in
                   ('teacher_id', 'campus', 'class_name', 'section', 'subject', 'time'))

    def schedule(day, allowed, include_choices=True):
        # Availability needs the teacher's cross-campus bookings. Restore the
        # caller's scope before rendering and explicitly restrict every row.
        original_scope = getattr(g, 'access_campuses', None)
        g.access_campuses = None
        try:
            date_key = day.isoformat()
            unavailable = {row.person_id: row.status
                           for row in Daily.query.filter(*absence_conditions(Daily.__table__, day))}
            for row in Workflow.query.filter(*leave_conditions(Workflow.__table__, day)):
                employee = str(row.data.get('employee_id', ''))
                if employee.isdigit():
                    unavailable.setdefault(int(employee), 'Approved leave')
            saved = {row.data['period_id']: row for row in cover_records(day)}
            if not unavailable and not saved:
                return []
            employees = {e.id: e for e in Employee.query.filter_by(status='Active')
                         if 'teacher' in (e.role or '').casefold()}
            campuses = defaultdict(set)
            if include_choices:
                for eid, info in app.extensions['record_helpers']['raw_many']('employee', list(employees.values())).items():
                    campuses[eid].add(info.get('campus', ''))
            cohorts = [row for row in Workflow.query.filter_by(kind='teacher-classes', status='Active')
                       if str(row.data.get('employee_id', '')).isdigit()
                       and int(row.data['employee_id']) in employees
                       and all(row.data.get(field) for field in ('campus', 'class_name', 'section'))]
            for cohort in cohorts:
                campuses[int(cohort.data['employee_id'])].add(cohort.data['campus'])
            periods = app.extensions['automatic_report_helpers']['teacher_timetable'](cohorts, include_ids=True)
            holidays = {row.scope for row in app.extensions['holiday_calendar_helpers']['rows']()
                        if (row.data['date'][5:] == date_key[5:] if row.data.get('repeats')
                            else row.data['date'] == date_key)}
            periods = [p for p in periods if p['weekday'] == day.weekday()
                       and '' not in holidays and p['campus'] not in holidays]
            booked = defaultdict(set)
            for period in periods:
                record = saved.get(period['period_id'])
                if record and matches_period(record, period):
                    booked[period['time']].add(record.data['substitute_id'])
            full_day = {p['teacher_id'] for p in periods if p['mode'] == 'full-class'}
            busy = defaultdict(set)
            for p in periods:
                if p['mode'] == 'lecture':
                    busy[p['time']].add(p['teacher_id'])
            accounts = {}
            if include_choices:
                staff_model = app.extensions['staff_account_model']
                accounts = {row.employee_id: set(row.data.get('campuses', []))
                            for row in staff_model.query.filter_by(active=True)}
        finally:
            g.access_campuses = original_scope

        rows = []
        for period in periods:
            campus, teacher, time = period['campus'], period['teacher_id'], period['time']
            if period['mode'] != 'lecture' or (allowed is not None and campus not in allowed):
                continue
            record = saved.get(period['period_id'])
            if teacher not in unavailable and record is None:
                continue
            assigned = record.data['substitute_id'] if record else None
            conflicts = busy[time] | full_day | set(unavailable)
            available = [
                employee for eid, employee in employees.items()
                if eid not in conflicts and (eid == assigned or eid not in booked[time])
                and campus in campuses[eid] and (eid not in accounts or campus in accounts[eid])
            ] if include_choices else []
            rows.append(dict(period, original=employees[teacher].name, reason=unavailable.get(teacher, ''),
                             record=record, available=sorted(available, key=lambda e: e.name.casefold()),
                             substitute=record.data['substitute_name'] if record else '',
                             conflict=(assigned in conflicts or assigned not in employees or not matches_period(record, period)) if record else False))
        return rows

    def within_scope(permission):
        allowed = scopes(app, permission)
        current = getattr(g, 'access_campuses', None)
        return allowed if current is None or allowed is None else allowed & current

    def uncovered(day, has_absence=True):
        allowed = within_scope('attendance.view')
        if allowed == set():
            return None
        if not has_absence:
            return 0
        return sum(bool(row['reason']) and (not row['record'] or row['conflict'])
                   for row in schedule(day, allowed, include_choices=False))

    def teacher_assignments(employee_id, campuses, day):
        finish = day + timedelta(days=6)
        records = Workflow.query.filter_by(kind=COVER, status='Active').filter(
            Workflow.data['day'].as_string().between(day.isoformat(), finish.isoformat()),
            Workflow.data['substitute_id'].as_integer() == employee_id,
            Workflow.data['campus'].as_string().in_(campuses)).all()
        ids = {record.id for record in records}
        assigned = []
        for key in sorted({record.data['day'] for record in records}):
            for row in schedule(date.fromisoformat(key), campuses, include_choices=False):
                record = row['record']
                if record and record.id in ids and not row['conflict']:
                    assigned.append(record.data)
        return sorted(assigned, key=lambda item: (item['day'], item['time']))

    @bp.get('')
    def index():
        try:
            day = date.fromisoformat(request.args.get('day', school_today().isoformat()))
        except ValueError:
            abort(422, 'Choose a valid cover date.')
        rows = schedule(day, within_scope('attendance.view'))
        return render_template('class_cover.html', title='Substitute Teacher / Class Cover', day=day, rows=rows,
                               editable=within_scope('attendance.update'))

    @bp.post('/save')
    def save():
        csrf()
        try:
            day = date.fromisoformat(request.form.get('day', ''))
        except ValueError:
            abort(422, 'Choose a valid cover date.')
        app.extensions['admission_capacity']['lock']()
        period_id = request.form.get('period', type=int)
        row = next((p for p in schedule(day, within_scope('attendance.update')) if p['period_id'] == period_id), None)
        if not row:
            abort(409, 'This period is no longer available. Reload the cover list.')
        record = row['record']
        teacher_id = request.form.get('substitute', type=int)
        if request.form.get('revision') != str(record.data['revision'] if record else 0):
            abort(409, 'This cover has changed. Reload before saving.')
        if request.form.get('action') == 'remove' and record:
            record.status = 'Voided'
            action = 'Remove class cover'
        elif request.form.get('action') == 'assign' and row['reason']:
            teacher = next((e for e in row['available'] if e.id == teacher_id), None)
            if not teacher:
                abort(409, 'This teacher is no longer free for this period. Reload and select another teacher.')
            if record is None:
                record = Workflow(kind=COVER, status='Active')
                db.session.add(record)
            record.data = dict(day=day.isoformat(), period_id=period_id, campus=row['campus'],
                               class_name=row['class_name'], section=row['section'], subject=row['subject'],
                               time=row['time'], time_label=row['time_label'], teacher_id=row['teacher_id'],
                               substitute_id=teacher.id, substitute_name=teacher.name,
                               revision=(record.data or {}).get('revision', 0) + 1)
            action = 'Assign class cover'
        else:
            abort(422, 'Choose an available teacher or remove the saved cover.')
        db.session.add(Audit(action=action, data=dict(campus=row['campus'], day=day.isoformat(),
                                                     period_id=period_id, substitute_id=record.data['substitute_id'])))
        db.session.commit()
        flash('Class cover updated.', 'success')
        return redirect(url_for('class_cover.index', day=day.isoformat()))

    app.extensions['class_cover_helpers'] = dict(uncovered=uncovered, teacher_assignments=teacher_assignments, has_unavailability=has_unavailability)
    app.register_blueprint(bp)
