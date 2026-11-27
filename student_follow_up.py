"""Attendance follow-ups backed by saved student attendance and case history."""
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from school_clock import school_today
from workspace_actor import actor, csrf, scopes

CASE_KIND = 'student-attendance-follow-up'
OUTCOMES = ('Pending', 'Call attempted', 'Spoke to parent', 'Call again')


def absence_streak(marks, holidays, today, start):
    result = []
    for offset in range((today - start).days + 1):
        day = today - timedelta(days=offset)
        status = marks.get(day)
        if day in holidays or status == 'Off Day':
            continue
        if status == 'Absent':
            result.append(day.isoformat())
        elif status or (day != today and day.weekday() != 6):
            break
    return list(reversed(result))


def configure_student_follow_up(app, db, Student, Employee):
    bp = Blueprint('student_follow_up', __name__, url_prefix='/workspace/student-follow-up')
    models = app.extensions['ops_models']
    Workflow, Daily, Audit = (models[key] for key in ('workflow', 'daily', 'audit'))

    def cases():
        today = school_today()
        start = today - timedelta(days=119)
        students = Student.query.filter_by(status='Active').order_by(Student.name, Student.id).all()
        profiles = app.extensions['record_helpers']['raw_many']('student', students)
        marks = defaultdict(dict)
        saved_marks = Daily.query.filter(Daily.kind == 'student', Daily.day.between(start, today),
                                        Daily.person_id.in_(profiles))
        for mark in saved_marks:
            marks[mark.person_id][mark.day] = mark.status
        calendars = defaultdict(set)
        for row in app.extensions['holiday_calendar_helpers']['rows']():
            day = date.fromisoformat(row.data['date'])
            for year in range(start.year, today.year + 1) if row.data.get('repeats') else (day.year,):
                try:
                    calendars[row.scope].add(day.replace(year=year))
                except ValueError:
                    continue  # A recurring 29 February is absent in a non-leap year.
        history = defaultdict(list)
        for case in Workflow.query.filter_by(kind=CASE_KIND).order_by(Workflow.id.desc()):
            history[case.data['student_id']].append(case)
        assigned = defaultdict(set)
        for row in Workflow.query.filter_by(kind='teacher-classes', status='Active'):
            data = row.data
            assigned[data.get('campus'), data.get('class_name'), data.get('section')].add(str(data.get('employee_id')))
        teachers = {str(e.id): e.name for e in Employee.query.filter_by(status='Active')
                    if 'teacher' in (e.role or '').casefold()}
        editable = scopes(app, 'attendance.update')
        contact = scopes(app, 'admissions.view')

        rows = []
        for student in students:
            info = profiles[student.id]
            campus, section = info.get('campus', ''), info.get('section', '')
            dates = absence_streak(marks[student.id], calendars[''] | calendars[campus], today, start)
            previous = history[student.id]
            current = next((case for case in previous if set(dates).intersection(case.data['dates'])), None)
            candidates = [(current, dates)] if len(dates) >= 3 else []
            candidates.extend((case, case.data['dates']) for case in previous if not candidates or case is not current)
            options = {tid: teachers[tid] for tid in assigned[campus, student.class_name, section] if tid in teachers}
            for case, streak in candidates:
                data = case.data if case else {}
                teacher_id = data.get('teacher_id', next(iter(options)) if len(options) == 1 else '')
                rows.append(dict(student=student, campus=campus, section=section, dates=streak,
                                 key=str(case.id) if case else f'{student.id}:{streak[0]}',
                                 outcome=case.status if case else 'Pending', revision=data.get('revision', 0),
                                 teacher_id=teacher_id, assignee=teachers.get(teacher_id, ''),
                                 choices=sorted(options.items(), key=lambda item: item[1].casefold()),
                                 due=data.get('due', ''), note=data.get('note', ''),
                                 can_edit=editable is None or campus in editable,
                                 phone=(info.get('phone') or student.phone or '') if contact is None or campus in contact else '',
                                 record=case))
        return rows

    @bp.get('')
    def index():
        show = request.args.get('show', 'open')
        if show not in ('open', 'all'):
            abort(400)
        rows = [row for row in cases() if show == 'all' or row['outcome'] != 'Spoke to parent']
        rows.sort(key=lambda row: (row['due'] or '9999-12-31', -len(row['dates']), row['student'].name.casefold()))
        return render_template('student_follow_up.html', title='Student Follow-up Center', rows=rows,
                               show=show, outcomes=OUTCOMES)

    @bp.post('/save')
    def save():
        csrf()
        app.extensions['admission_capacity']['lock']()
        key = request.form.get('case')
        row = next((item for item in cases() if item['key'] == key and item['can_edit']), None)
        if not row or request.form.get('revision') != str(row['revision']):
            abort(409, 'This follow-up changed. Reload the center and try again.')
        outcome, teacher_id = request.form.get('outcome'), request.form.get('teacher_id', '')
        due, note = request.form.get('due', ''), request.form.get('note', '').strip()
        if outcome not in OUTCOMES or len(note) > 500:
            abort(422, 'Choose a call outcome and enter at most 500 characters of notes.')
        if teacher_id and teacher_id not in dict(row['choices']) and teacher_id != row['teacher_id']:
            abort(422, 'Choose an assigned teacher for this class and section.')
        if outcome == 'Call again':
            try:
                due = date.fromisoformat(due).isoformat()
            except ValueError:
                abort(422, 'Choose a date for the next call.')
        else:
            due = ''
        operator = actor(app)['key']
        data = dict(student_id=row['student'].id, campus=row['campus'], dates=row['dates'],
                    teacher_id=teacher_id, due=due, note=note, revision=row['revision'] + 1)
        case = row['record']
        if case is None:
            case = Workflow(kind=CASE_KIND)
            db.session.add(case)
        case.status, case.data = outcome, data
        db.session.flush()
        db.session.add(Audit(action='Save student attendance follow-up', data={
            'case_id': case.id, 'student_id': row['student'].id, 'campus': row['campus'],
            'outcome': outcome, 'teacher_id': teacher_id, 'due': due, 'actor': operator}))
        db.session.commit()
        flash('Student follow-up saved.', 'success')
        return redirect(url_for('student_follow_up.index', show='all' if outcome == 'Spoke to parent' else 'open'))

    app.register_blueprint(bp)
