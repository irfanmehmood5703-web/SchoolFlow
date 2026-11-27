"""Separate attendance working dates from salary-paid dates."""
import calendar
import hmac
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import school_today

PAY_BASES = ("calendar_days", "working_days")
FIXED_SALARY_DAYS = 30


def month_dates(value):
    try:
        first=date.fromisoformat(value+'-01')
        if len(value)!=7 or first.strftime('%Y-%m')!=value:raise ValueError()
    except (ValueError,TypeError):raise ValueError('Choose a valid calendar month.')
    return [first.replace(day=n) for n in range(1,calendar.monthrange(first.year,first.month)[1]+1)]


def salary_paid_dates(month,working_dates,pay_basis='working_days'):
    valid={d.isoformat() for d in month_dates(month)}
    working=sorted(set(working_dates))
    if not working or not set(working)<=valid:raise ValueError('Configure valid working dates for this salary month first.')
    if pay_basis not in PAY_BASES:raise ValueError('Choose a valid salary pay basis.')
    return sorted(valid) if pay_basis=='calendar_days' else working


def salary_rate_days(pay_basis,working_dates=None):
    """Normal monthly pay has a fixed 30-day daily rate, regardless of month length."""
    if pay_basis=='calendar_days':return FIXED_SALARY_DAYS
    if pay_basis=='working_days' and working_dates:return len(set(working_dates))
    raise ValueError('Configure a valid working calendar for the salary rate.')


def joining_pay(month,joined,basic,working_dates,pay_basis='working_days'):
    dates=month_dates(month)
    if joined>dates[-1]:raise ValueError('Salary month precedes the joining date.')
    working=sorted(set(working_dates))
    paid=salary_paid_dates(month,working,pay_basis)
    eligible=[d for d in working if d>=joined.isoformat()]
    eligible_paid=[d for d in paid if d>=joined.isoformat()]
    amount=int((Decimal(basic)*len(eligible_paid)/len(paid)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return dict(method='paid-calendar-days' if pay_basis=='calendar_days' else 'working-days',
                pay_basis=pay_basis,working_dates=working,eligible_dates=eligible,
                total_working_days=len(working),eligible_working_days=len(eligible),
                paid_dates=paid,eligible_paid_dates=eligible_paid,total_paid_days=len(paid),eligible_paid_days=len(eligible_paid),
                monthly_basic=basic,payable_basic=amount)


def configure_payroll_calendar(app,db):
    bp=Blueprint('payroll_calendar',__name__,url_prefix='/workspace/payroll-calendar')

    class PayrollCalendar(db.Model):
        month=db.Column(db.String(7),primary_key=True)
        working_dates=db.Column(db.JSON,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    app.extensions['payroll_calendar_model']=PayrollCalendar

    def basis_setting(month):
        model=app.extensions['school_settings_models']['setting']
        return db.session.get(model,'hrm:payroll-pay-basis:'+month)

    def pay_basis(month):
        saved=basis_setting(month)
        # Existing calendars retain their original calculation until explicitly changed.
        return saved.data['basis'] if saved else 'working_days'

    app.extensions['payroll_calendar_helpers']=dict(pay_basis=pay_basis)

    @bp.route('',methods=['GET','POST'])
    def edit():
        error=None
        try:
            month=request.values.get('month',school_today().strftime('%Y-%m'))
            days=month_dates(month)
            if request.method=='POST':
                token=request.form.get('_csrf','')
                if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the calendar form.')
                app.extensions['admission_capacity']['lock']()
                saved=db.session.get(PayrollCalendar,month,populate_existing=True)
                selected=request.form.getlist('working_dates')
                if len(selected)!=len(set(selected)) or not selected or not set(selected)<={d.isoformat() for d in days}:
                    raise ValueError('Select at least one valid working date from this month.')
                if int(request.form.get('version','-1'))!=(saved.version if saved else 0):
                    raise ValueError('The working calendar changed in another tab. Reload before saving.')
                basis=request.form.get('pay_basis',pay_basis(month))
                salary_paid_dates(month,selected,basis)
                setting=basis_setting(month)
                old_basis=pay_basis(month)
                if saved:
                    if old_basis!=basis:
                        saved.version+=1
                    saved.working_dates=sorted(selected)
                else:db.session.add(PayrollCalendar(month=month,working_dates=sorted(selected)))
                if setting:setting.data={'basis':basis}
                else:
                    model=app.extensions['school_settings_models']['setting']
                    db.session.add(model(key='hrm:payroll-pay-basis:'+month,data={'basis':basis}))
                audit=app.extensions['ops_models']['audit']
                db.session.add(audit(action='Save payroll working calendar',data={'month':month,'working_dates':sorted(selected),'pay_basis':basis}))
                db.session.commit();flash('Working calendar and salary pay basis saved. Existing salary snapshots are unchanged.','success')
                return redirect(url_for('payroll_calendar.edit',month=month))
        except (ValueError,IntegrityError,StaleDataError) as exc:
            db.session.rollback()
            return render_template('operation_error.html',title='Check working calendar',error=str(exc) if isinstance(exc,ValueError) else 'Calendar changed. Reload and try again.'),422
        saved=db.session.get(PayrollCalendar,month)
        return render_template('payroll_calendar.html',title='Payroll Working Calendar',month=month,days=days,
                               selected=saved.working_dates if saved else [],version=saved.version if saved else 0,
                               weekdays=list(calendar.day_name),pay_basis=pay_basis(month) if saved else 'calendar_days',
                               fixed_salary_days=FIXED_SALARY_DAYS)

    app.register_blueprint(bp)


def all_present_bonus(month,joined,monthly_basic,allowances,working_dates,attendance,pay_basis='working_days'):
    """One working day's eligible pay; missing attendance never earns a bonus."""
    calendar=joining_pay(month,joined,monthly_basic,working_dates,pay_basis)
    eligible=set(calendar['eligible_dates'])
    records={row.day.isoformat():row.status for row in attendance}
    missing=sorted(eligible-set(records))
    disqualified=sorted(day for day,status in records.items() if status not in ('Present','Off Day') and (pay_basis=='working_days' or day in eligible))
    qualifies=bool(eligible) and not missing and not disqualified and any(records.get(day)=='Present' for day in eligible)
    basis=monthly_basic+sum(line['amount'] for line in allowances if line.get('type')=='Earning' and line.get('bonusable'))
    rate_days=salary_rate_days(pay_basis,calendar['working_dates'])
    amount=int((Decimal(basis)/rate_days).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if qualifies else 0
    return dict(method='one-working-day',amount=amount,basis=basis,working_days=calendar['total_working_days'],salary_divisor_days=rate_days,pay_basis=pay_basis,eligible_dates=sorted(eligible),missing_dates=missing,disqualified_dates=disqualified,qualified=qualifies)
