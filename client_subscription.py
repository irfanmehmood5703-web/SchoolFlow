"""Read-only client billing; only server operator commands create real charges."""
import calendar,re
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
import click
from flask import Blueprint,abort,render_template,request,session
from sqlalchemy.exc import IntegrityError
from operations import money

def configure_client_subscription(app,db):
    bp=Blueprint('client_subscription',__name__,url_prefix='/workspace/core/subscription');control={'info':{'identity_control':True}};School=app.extensions['identity_models']['institute']
    class Service(db.Model):
        __tablename__='client_service'
        __table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        institute_id=db.Column(db.Integer,db.ForeignKey('identity_institute.id'),nullable=False)
        name=db.Column(db.String(160),nullable=False)
        cycle=db.Column(db.String(20),nullable=False)
        price=db.Column(db.BigInteger,nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
    class Bank(db.Model):
        __tablename__='client_billing_profile'
        __table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
    class Invoice(db.Model):
        __tablename__='client_invoice'
        __table_args__=(db.UniqueConstraint('institute_id','month'),db.CheckConstraint('amount >= 0 AND discount >= 0 AND paid >= 0 AND paid + discount <= amount'),control)
        id=db.Column(db.Integer,primary_key=True)
        institute_id=db.Column(db.Integer,db.ForeignKey('identity_institute.id'),nullable=False)
        month=db.Column(db.String(7),nullable=False)
        due=db.Column(db.Date,nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        paid=db.Column(db.BigInteger,nullable=False,default=0)
        discount=db.Column(db.BigInteger,nullable=False,default=0)
        snapshot=db.Column(db.JSON,nullable=False,default=dict)
        @property
        def remaining(self):return self.amount-self.paid-self.discount
    class Receipt(db.Model):
        __tablename__='client_payment'
        __table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        invoice_id=db.Column(db.Integer,db.ForeignKey('client_invoice.id'),nullable=False)
        reference=db.Column(db.String(120),nullable=False,unique=True)
        amount=db.Column(db.BigInteger,nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    app.extensions['client_subscription_models']=dict(service=Service,invoice=Invoice,receipt=Receipt,bank=Bank)
    def school():
        if not session.get('owner_id') or session.get('staff_id') or not session.get('institute_id'):abort(403,'Client subscription is available only to the primary institute owner.')
        return db.get_or_404(School,session['institute_id'])
    def bounds():
        today=datetime.now(ZoneInfo('Asia/Karachi')).date();start=request.args.get('from',today.replace(month=1,day=1).isoformat());end=request.args.get('to',today.replace(day=calendar.monthrange(today.year,today.month)[1]).isoformat())
        try:a=date.fromisoformat(start);b=date.fromisoformat(end)
        except ValueError:abort(422,'Choose valid dates.')
        if a>b or (b-a).days>3660:abort(422,'Choose a date range up to ten years.')
        return a,b
    @bp.get('')
    def index():
        owner_school=school();start,end=bounds();rows=Invoice.query.filter_by(institute_id=owner_school.id).filter(Invoice.due>=start,Invoice.due<=end).order_by(Invoice.month,Invoice.id).all();ids=[r.id for r in rows]
        payments=Receipt.query.filter(Receipt.invoice_id.in_(ids)).order_by(Receipt.created).all() if ids else [];last={p.invoice_id:p.created.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')) for p in payments};bank=db.session.get(Bank,1)
        return render_template('client_subscription.html',title='SchoolFlow Subscription',school=owner_school,services=Service.query.filter_by(institute_id=owner_school.id).all(),rows=rows,last=last,bank=bank.data if bank else {},start=start,end=end,total={k:sum(getattr(r,k) for r in rows) for k in ('amount','paid','discount','remaining')})
    @bp.get('/receipts/<int:invoice_id>')
    def receipt(invoice_id):
        owner_school=school();row=Invoice.query.filter_by(id=invoice_id,institute_id=owner_school.id).first_or_404()
        return render_template('client_receipt.html',title='SchoolFlow Subscription Statement',school=owner_school,row=row,receipts=Receipt.query.filter_by(invoice_id=row.id).order_by(Receipt.created).all(),stamp=lambda value:value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M'))
    def operator_school(code):
        school=School.query.filter_by(code=code.strip().upper()).first()
        if not school:raise click.ClickException('Institute not found.')
        return school
    @app.cli.command('subscription-service')
    @click.option('--code',required=True)
    @click.option('--name',required=True)
    @click.option('--cycle',type=click.Choice(['Monthly','Annual','One-time','Usage']),required=True)
    @click.option('--price',required=True)
    def add_service(code,name,cycle,price):
        if not name.strip() or len(name)>160:raise click.ClickException('Use a service name up to 160 characters.')
        try:amount=money(price)
        except ValueError as e:raise click.ClickException(str(e))
        school=operator_school(code);db.session.add(Service(institute_id=school.id,name=name.strip(),cycle=cycle,price=amount,active=True));db.session.commit();click.echo('Client service recorded. No payment or invoice was invented.')
    @app.cli.command('subscription-bank')
    @click.option('--bank',required=True)
    @click.option('--title',required=True)
    @click.option('--iban',default='')
    @click.option('--account',default='')
    @click.option('--contact',default='')
    def set_bank(bank,title,iban,account,contact):
        if any(len(x)>180 for x in (bank,title,iban,account,contact)):raise click.ClickException('Billing detail is too long.')
        row=db.session.get(Bank,1)
        if not row:row=Bank(id=1);db.session.add(row)
        row.data=dict(bank=bank,title=title,iban=iban,account=account,contact=contact);db.session.commit();click.echo('SchoolFlow vendor billing details recorded.')
    @app.cli.command('subscription-invoice')
    @click.option('--code',required=True)
    @click.option('--month',required=True)
    @click.option('--due',required=True)
    @click.option('--amount',required=True)
    @click.option('--discount',default='0')
    def invoice(code,month,due,amount,discount):
        try:
            date.fromisoformat(month+'-01');due=date.fromisoformat(due);amount=money(amount);discount=money(discount)
            if not re.fullmatch(r'\d{4}-\d{2}',month) or discount>amount:raise ValueError('Check invoice month and discount.')
        except ValueError as e:raise click.ClickException(str(e))
        school=operator_school(code);bank=db.session.get(Bank,1);snapshot=dict(school=school.name,code=school.code,bank=bank.data if bank else {},services=[dict(name=r.name,cycle=r.cycle,price=r.price) for r in Service.query.filter_by(institute_id=school.id,active=True).all()]);row=Invoice(institute_id=school.id,month=month,due=due,amount=amount,discount=discount,paid=0,snapshot=snapshot);db.session.add(row)
        try:db.session.commit()
        except IntegrityError:db.session.rollback();raise click.ClickException('This institute/month already has an invoice.')
        click.echo('Invoice '+str(row.id)+' created; it is unpaid until an actual receipt is recorded.')
    @app.cli.command('subscription-receive')
    @click.option('--invoice-id',type=int,required=True)
    @click.option('--amount',required=True)
    @click.option('--reference',required=True)
    def receive(invoice_id,amount,reference):
        try:amount=money(amount)
        except ValueError as e:raise click.ClickException(str(e))
        if not amount or not reference or len(reference)>120:raise click.ClickException('Use a positive amount and unique payment reference up to 120 characters.')
        # A conditional SQL update protects the remaining balance across two
        # concurrent control-store operators without relying on tenant locks.
        old=Receipt.query.filter_by(reference=reference).first()
        if old:
            if old.invoice_id!=invoice_id or old.amount!=amount:raise click.ClickException('Reference already used with different payment data.')
            click.echo('Receipt already recorded; no second payment posted.');return
        count=Invoice.query.filter_by(id=invoice_id).filter(Invoice.amount-Invoice.paid-Invoice.discount>=amount).update({Invoice.paid:Invoice.paid+amount},synchronize_session=False)
        if count!=1:db.session.rollback();raise click.ClickException('Invoice not found or payment exceeds the remaining amount.')
        db.session.add(Receipt(invoice_id=invoice_id,reference=reference,amount=amount))
        try:db.session.commit()
        except IntegrityError:db.session.rollback();raise click.ClickException('Payment reference was recorded concurrently. Verify the existing receipt.')
        click.echo('Actual subscription payment recorded.')
    app.register_blueprint(bp)
