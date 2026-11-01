"""Stable internal consumer references and authenticated payment-link QR images.

These references are not bank registration or payment reconciliation. Schools
supply their own HTTPS collection URL; SchoolFlow does not invent bank payloads.
"""
import io,re,secrets,hashlib,hmac,json
from urllib.parse import urlsplit,quote
from flask import abort,request,send_file,session as web_session,g,render_template,redirect,url_for,flash
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
import qrcode


def configure_challan_consumers(app,db):
    Bill=app.extensions['ops_models']['bill'];Item=app.extensions['school_settings_models']['item'];Details=app.extensions['record_models']['student']
    class ConsumerAccount(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        key=db.Column(db.String(600),nullable=False,unique=True)
        value=db.Column(db.String(100),nullable=False,unique=True)
    class ChallanConsumer(db.Model):
        bill_id=db.Column(db.Integer,db.ForeignKey('bill.id'),primary_key=True)
        account_id=db.Column(db.Integer,db.ForeignKey('consumer_account.id'),nullable=False)
        mode=db.Column(db.String(20),nullable=False)
        bill=db.relationship(Bill,backref=db.backref('consumer_identity',uselist=False,cascade='all, delete-orphan'))
        account=db.relationship(ConsumerAccount)
    app.extensions['challan_consumer_models']=dict(account=ConsumerAccount,reference=ChallanConsumer)
    def config(campus):
        rows={r.scope:r.data for r in db.session.query(Item).filter_by(kind='challan-branding',name='Fee Challan').all()}
        return rows.get(campus,rows.get('',{}))
    def ensure(bill,session):
        if session.get(ChallanConsumer,bill.id):return
        details=session.query(Details).filter_by(student_id=bill.student_id).first();d=details.data if details else {};cfg=config(d.get('campus',''));mode=cfg.get('consumer_mode','bill')
        family=str(details.family_id) if details and details.family_id else ''
        if not family and d.get('family_no'):family=d.get('campus','')+'|'+str(d['family_no'])
        if mode=='family' and family:key='family:'+family
        else:mode='bill';key='bill:'+secrets.token_hex(16)
        account=next((r for r in session.new if isinstance(r,ConsumerAccount) and r.key==key),None) or session.query(ConsumerAccount).filter_by(key=key).first()
        if not account:
            prefix=cfg.get('consumer_prefix','SF');account=ConsumerAccount(key=key,value=prefix+'-'+secrets.token_hex(8).upper());session.add(account)
        session.add(ChallanConsumer(bill=bill,account=account,mode=mode))
    @event.listens_for(db.session.session_factory.class_,'before_flush')
    def remember(session,flush_context,instances):
        session.info.setdefault('schoolflow_new_bills',set()).update(b for b in session.new if isinstance(b,Bill))
    @event.listens_for(db.session.session_factory.class_,'after_flush_postexec')
    def assign(session,flush_context):
        pending=session.info.pop('schoolflow_new_bills',set())
        for bill in sorted(pending,key=lambda b:b.id):ensure(bill,session)
    @event.listens_for(db.session.session_factory.class_,'after_soft_rollback')
    def clear_pending(session,previous_transaction):session.info.pop('schoolflow_new_bills',None)
    def many(bills):
        rows=ChallanConsumer.query.filter(ChallanConsumer.bill_id.in_([b.id for b in bills])).all()
        accounts={r.id:r.value for r in ConsumerAccount.query.filter(ConsumerAccount.id.in_({r.account_id for r in rows})).all()}
        return {r.bill_id:accounts[r.account_id] for r in rows}
    def valid_url(value):
        if not value:return ''
        if len(value)>1500 or any(c.isspace() for c in value):raise ValueError('Enter a single HTTPS bank/payment link up to 1,500 characters.')
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or any(c in parsed.hostname for c in '{}') or parsed.username or parsed.password or parsed.fragment:raise ValueError('Use an HTTPS bank/payment link without credentials or fragments.')
        scrub=value
        for token in ('{consumer}','{bill}','{amount}'):scrub=scrub.replace(token,'')
        try:parsed.port
        except ValueError:raise ValueError('Use a valid HTTPS payment-link port.')
        if '{' in scrub or '}' in scrub:raise ValueError('Payment links support only {consumer}, {bill} and {amount} placeholders.')
        return value
    def payment_url(bill,consumer,cfg):
        if not cfg.get('show_payment_qr') or not consumer or bill.remaining<=0:return ''
        value=valid_url(cfg.get('payment_url',''))
        for key,replacement in dict(consumer=consumer,bill=str(bill.id),amount=f'{bill.remaining/100:.2f}').items():value=value.replace('{'+key+'}',quote(replacement,safe=''))
        return value
    @app.get('/workspace/core/fees/challan-payment-qr/<int:bill_id>')
    def challan_payment_qr(bill_id):
        bill=db.get_or_404(Bill,bill_id);d=Details.query.filter_by(student_id=bill.student_id).first();cfg=config(d.data.get('campus','') if d else '')
        link=payment_url(bill,many([bill]).get(bill.id,''),cfg)
        if not link:abort(404)
        stream=io.BytesIO();qrcode.make(link).save(stream,format='PNG');stream.seek(0)
        response=send_file(stream,mimetype='image/png',download_name=f'schoolflow-payment-qr-{bill.id}.png');response.headers['Cache-Control']='no-store';return response
    def legacy_rows():return Bill.query.outerjoin(ChallanConsumer,ChallanConsumer.bill_id==Bill.id).filter(ChallanConsumer.bill_id==None).order_by(Bill.id).limit(100).all()
    def legacy_stamp(bills):
        out=[]
        for b in bills:
            d=Details.query.filter_by(student_id=b.student_id).first();data=d.data if d else {};cfg=config(data.get('campus',''))
            out.append([b.id,b.version,b.student_id,d.family_id if d else None,data.get('campus',''),data.get('family_no',''),cfg.get('consumer_mode','bill'),cfg.get('consumer_prefix','SF')])
        return out
    @app.route('/workspace/core/fees/challan-consumer-backfill',methods=['GET','POST'])
    def consumer_backfill():
        def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=web_session.get('owner_id'),csrf=web_session.get('record_csrf'))
        signer=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-consumer-backfill-v1')
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],web_session.get('record_csrf','')):abort(400,'Reload the reference review.')
            app.extensions['admission_capacity']['lock']()
            try:
                raw=request.form.get('preview_token','')
                if len(raw)>131072:raise ValueError('Invalid reference review.')
                try:payload=signer.loads(raw,max_age=900)
                except BadData:raise ValueError('This reference review expired or changed. Reload it.')
                bills=legacy_rows();stamp=legacy_stamp(bills)
                if payload!=dict(actor=actor(),stamp=stamp):raise ValueError('The bills, family links or reference settings changed. Review again.')
                for b in bills:ensure(b,db.session)
                db.session.add(app.extensions['ops_models']['audit'](action='Assign legacy consumer references',data=dict(bill_ids=[b.id for b in bills],owner_id=web_session.get('owner_id'))));db.session.commit()
                flash('Reviewed consumer references assigned. No fee amount or payment was changed.','success');return redirect(url_for('consumer_backfill'))
            except (IntegrityError,StaleDataError):
                db.session.rollback();return render_template('operation_error.html',title='Review consumer references',error='A reference or challan changed. Reload the review; no partial batch was saved.'),422
            except ValueError as error:
                db.session.rollback();return render_template('operation_error.html',title='Review consumer references',error=str(error)),422
        bills=legacy_rows();token=signer.dumps(dict(actor=actor(),stamp=legacy_stamp(bills)))
        return render_template('consumer_backfill.html',title='Legacy consumer reference review',bills=bills,token=token)
    app.extensions['challan_consumer_helpers']=dict(many=many,validate_url=valid_url,payment_url=payment_url)
