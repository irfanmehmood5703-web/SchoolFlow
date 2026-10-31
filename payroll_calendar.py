"""Explicit school working dates and reproducible joining-month basic pay."""
import calendar
import hmac
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def month_dates(value):
    try:
        first=date.fromisoformat(value+'-01')
        if len(value)!=7 or first.strftime('%Y-%m')!=value:raise ValueError()
    except (ValueError,TypeError):raise ValueError('Choose a valid calendar month.')
    return [first.replace(day=n) for n in range(1,calendar.monthrange(first.year,first.month)[1]+1)]


def joining_pay(month,joined,basic,working_dates):
    dates=month_dates(month)
    if joined>dates[-1]:raise ValueError('Salary month precedes the joining date.')
    working=sorted(set(working_dates))
    valid={d.isoformat() for d in dates}
    if not working or not set(working)<=valid:raise ValueError('Configure valid working dates for this salary month first.')
    eligible=[d for d in working if d>=joined.isoformat()]
    amount=int((Decimal(basic)*len(eligible)/len(working)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return dict(method='working-days',working_dates=working,eligible_dates=eligible,
                total_working_days=len(working),eligible_working_days=len(eligible),
                monthly_basic=basic,payable_basic=amount)


def configure_payroll_calendar(app,db):
    bp=Blueprint('payroll_calendar',__name__,url_prefix='/workspace/payroll-calendar')

    class PayrollCalendar(db.Model):
        month=db.Column(db.String(7),primary_key=True)
        working_dates=db.Column(db.JSON,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    app.extensions['payroll_calendar_model']=PayrollCalendar

    @bp.route('',methods=['GET','POST'])
    def edit():
        error=None
        try:
            month=request.values.get('month',date.today().strftime('%Y-%m'))
            days=month_dates(month)
            saved=db.session.get(PayrollCalendar,month)
            if request.method=='POST':
                token=request.form.get('_csrf','')
                if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the calendar form.')
                selected=request.form.getlist('working_dates')
                if len(selected)!=len(set(selected)) or not selected or not set(selected)<={d.isoformat() for d in days}:
                    raise ValueError('Select at least one valid working date from this month.')
                if int(request.form.get('version','-1'))!=(saved.version if saved else 0):
                    raise ValueError('The working calendar changed in another tab. Reload before saving.')
                if saved:saved.working_dates=sorted(selected)
                else:db.session.add(PayrollCalendar(month=month,working_dates=sorted(selected)))
                audit=app.extensions['ops_models']['audit']
                db.session.add(audit(action='Save payroll working calendar',data={'month':month,'working_dates':sorted(selected)}))
                db.session.commit();flash('Working calendar saved. Existing salary snapshots are unchanged.','success')
                return redirect(url_for('payroll_calendar.edit',month=month))
        except (ValueError,IntegrityError,StaleDataError) as exc:
            db.session.rollback()
            return render_template('operation_error.html',title='Check working calendar',error=str(exc) if isinstance(exc,ValueError) else 'Calendar changed. Reload and try again.'),422
        return render_template('payroll_calendar.html',title='Payroll Working Calendar',month=month,days=days,
                               selected=saved.working_dates if saved else [],version=saved.version if saved else 0,
                               weekdays=list(calendar.day_name))

    app.register_blueprint(bp)
