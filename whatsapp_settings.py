"""Write-only encrypted provider keys and explicit WhatsApp account commands.

No provider, executable or outbound message is fabricated when unconfigured.
The optional adapter follows https://walinkapi.com/api, not an inferred API.
"""
import base64,hmac,io,json,os,re,secrets,urllib.request,urllib.parse
from datetime import datetime,timedelta,timezone
from cryptography.fernet import Fernet,InvalidToken
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
ENDPOINT='https://walinkapi.com/admin/api.php'
RETENTION={3:'3 days',7:'1 week (recommended)',14:'2 weeks',30:'1 month',90:'3 months',0:'Keep everything (not recommended)'}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def provider_request(endpoint,key,action,fields=None):
    if endpoint!=ENDPOINT:raise ValueError('This provider URL has no verified adapter. Use the documented WA Link API endpoint.')
    fields=fields or {};params=urllib.parse.urlencode(dict(do=action,key=key,**({} if action=='send' else fields)))
    data=json.dumps(fields).encode() if action=='send' else None
    req=urllib.request.Request(endpoint+'?'+params,data=data,headers={'Accept':'application/json','Content-Type':'application/json','User-Agent':'SchoolFlow-WhatsApp/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=10) as response:
            raw=response.read(262145)
            if len(raw)>262144:raise ValueError()
            result=json.loads(raw)
            if not isinstance(result,(dict,list)):raise ValueError()
            return result
    except Exception:raise ValueError('Provider did not return a verified response. Check your provider dashboard before retrying; credentials are not shown.') from None

def configure_whatsapp(app,db):
    bp=Blueprint('whatsapp_settings',__name__,url_prefix='/workspace/core/whatsapp');Setting=app.extensions['school_settings_models']['setting'];Audit=app.extensions['ops_models']['audit']
    class Provider(db.Model):
        __tablename__='whatsapp_provider'
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String(120),nullable=False,unique=True)
        endpoint=db.Column(db.String(200),nullable=False)
        secret=db.Column(db.Text,nullable=False)
        state=db.Column(db.Text)
        active=db.Column(db.Boolean,nullable=False,default=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Command(db.Model):
        __tablename__='whatsapp_command'
        id=db.Column(db.Integer,primary_key=True)
        provider_id=db.Column(db.Integer,db.ForeignKey('whatsapp_provider.id'),nullable=False)
        token=db.Column(db.String(64),nullable=False,unique=True)
        action=db.Column(db.String(30),nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        status=db.Column(db.String(40),nullable=False)
        payload=db.Column(db.Text)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    app.extensions['whatsapp_models']=dict(provider=Provider,command=Command)
    def cipher():
        key=app.config.get('INTEGRATION_KEY') or os.getenv('SCHOOLFLOW_INTEGRATION_KEY')
        if not key:raise ValueError('The software owner must configure the private integration encryption key before saving API credentials.')
        try:return Fernet(key.encode() if isinstance(key,str) else key)
        except Exception:raise ValueError('The private integration encryption key is invalid.') from None
    def scope():
        identity=getattr(g,'school_identity',None)
        if not identity or identity.get('demo') or not identity.get('scope'):abort(403,'Provider credentials require a private institute sign-in.')
        return identity['scope']
    def encrypt(value):return cipher().encrypt(json.dumps(dict(scope=scope(),value=value)).encode()).decode()
    def decrypt(value):
        try:
            data=json.loads(cipher().decrypt(value.encode()))
            if data['scope']!=scope():raise ValueError()
            return data['value']
        except InvalidToken:raise ValueError('Provider credentials could not be decrypted. Restore the integration key or replace the saved account key.') from None
    def config():
        row=db.session.get(Setting,'whatsapp-service');return row,{'provider':'schoolflow','retention':7,'active':None,**(row.data if row else {})}
    def save(data):
        row,_=config()
        if row:row.data=data
        else:db.session.add(Setting(key='whatsapp-service',data=data))
    def version(row):
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This record changed. Reload before saving.')
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('A record or request changed. Reload before retrying.')
    def audit(action,**data):db.session.add(Audit(action=action,data=data))
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
            principal=getattr(g,'staff_principal',None)
            if principal is not None and request.form.get('operation')=='send':
                helper=app.extensions['staff_access_helpers']
                if helper['grant'](principal,'core.update')!=set(helper['campuses']()):abort(403,'School-wide Core Settings and Communication Create rights are required for manual WhatsApp sending.')
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check WhatsApp settings',error=str(error)),422
    @bp.route('/service',methods=['GET','POST'])
    def service():
        row,data=config()
        if request.method=='POST':
            version(row);provider=request.form.get('provider','');raw=request.form.get('retention','')
            if provider not in ('schoolflow','walink') or not raw.isdigit() or int(raw) not in RETENTION:raise ValueError('Choose a supported sender and history retention.')
            if provider=='walink' and not data.get('active'):raise ValueError('Add and select your own provider account in Manage WhatsApp first.')
            new={**data,'provider':provider,'retention':int(raw)};save(new);audit('Change WhatsApp service',before=data,after=new);commit();return redirect(url_for('whatsapp_settings.service'))
        url=os.getenv('SCHOOLFLOW_WHATSAPP_WINDOWS_URL','')
        if not url.startswith('https://github.com/irfanmehmood5703-web/SchoolFlow/releases/download/'):url=''
        return render_template('whatsapp_service.html',title='WhatsApp Service',row=row,settings=data,retention=RETENTION,download=url)
    def redacted(value,key):
        if isinstance(value,dict):return {str(k):redacted(v,key) for k,v in value.items() if not re.search('key|token|secret|password|authorization',str(k),re.I)}
        if isinstance(value,list):return [redacted(v,key) for v in value[:200]]
        return value.replace(key,'[redacted]')[:20000] if isinstance(value,str) else value
    def state(provider):return decrypt(provider.state) if provider.state else {}
    def linked(data):
        values=data.get('account_view',{})
        if isinstance(values,dict):values=values.get('accounts',values.get('data',[]))
        return [v for v in values if isinstance(v,dict) and str(v.get('id','')).strip()] if isinstance(values,list) else []
    def qr_data(data):
        value=data.get('account_new',{})
        if isinstance(value,dict):value=value.get('qr',value.get('qr_code',value.get('qrcode','')))
        if not isinstance(value,str):return None
        if value.startswith('data:image/png;base64,'):
            try:
                raw=base64.b64decode(value.split(',',1)[1],validate=True)
                if len(raw)>200000:raise ValueError()
                im=Image.open(io.BytesIO(raw))
                if im.format!='PNG' or im.width*im.height>4000000:raise ValueError()
                im.verify()
                return value
            except Exception:return None
        if value and len(value)<4096 and not value.startswith(('http:','https:')):
            import qrcode
            out=io.BytesIO();qrcode.make(value).save(out,format='PNG');return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
        return None
    def current():
        _,cfg=config();p=db.session.get(Provider,cfg['active']) if cfg.get('active') else None;return p if p and p.active else None
    @bp.route('',methods=['GET','POST'])
    def manager():
        row,cfg=config()
        if request.method=='POST':
            action=request.form.get('action')
            if action=='save-provider':
                scope();name=request.form.get('name','').strip();key=request.form.get('api_key','').strip();endpoint=request.form.get('endpoint','')
                if not name or len(name)>120 or endpoint!=ENDPOINT or not 16<=len(key)<=512:raise ValueError('Enter an account name, a private API key and the documented provider endpoint.')
                p=Provider(name=name,endpoint=endpoint,secret=encrypt(key));db.session.add(p);db.session.flush();save({**cfg,'active':p.id});audit('Save WhatsApp provider',provider_id=p.id,name=name);commit()
            elif action=='activate':
                version(row);raw=request.form.get('provider_id','')
                if not raw.isdigit():raise ValueError('Choose a saved provider account.')
                p=db.get_or_404(Provider,int(raw))
                if not p.active:raise ValueError('This provider was removed.')
                save({**cfg,'active':p.id});audit('Select WhatsApp provider',provider_id=p.id);commit()
            elif action=='delete-provider':
                raw=request.form.get('provider_id','')
                if not raw.isdigit():raise ValueError('Choose a saved provider.')
                p=db.get_or_404(Provider,int(raw));version(p)
                if cfg.get('active')==p.id:save({**cfg,'active':None,'provider':'schoolflow'})
                p.active=False;p.secret='';p.state=None;audit('Remove WhatsApp provider',provider_id=p.id);commit()
            else:raise ValueError('Choose a supported account action.')
            return redirect(url_for('whatsapp_settings.manager'))
        p=current();data=state(p) if p else {};status=request.args.get('status','all')
        if status not in ('all','Submitted','Sent','Delivered','Read','Failed','Unknown','Pending'):raise ValueError('Choose a valid message status.')
        query=Command.query.filter_by(action='send').filter(Command.payload.isnot(None))
        if status!='all':query=query.filter_by(status=status)
        history=[]
        for item in query.order_by(Command.id.desc()).limit(100).all():history.append((item,decrypt(item.payload)))
        return render_template('whatsapp_manager.html',title='Manage WhatsApp',row=row,settings=cfg,providers=Provider.query.filter_by(active=True).order_by(Provider.name).all(),active=p,state=data,linked=linked(data),qr=qr_data(data),history=history,status=status,endpoint=ENDPOINT,token=secrets.token_hex(24),outbound=bool(app.config.get('WHATSAPP_ENABLED') or os.getenv('SCHOOLFLOW_WHATSAPP_ENABLED')=='1'),send_enabled=bool(app.config.get('WHATSAPP_SEND_ENABLED') or os.getenv('SCHOOLFLOW_WHATSAPP_SEND_ENABLED')=='1'))
    @bp.post('/command')
    def command():
        if not (app.config.get('WHATSAPP_ENABLED') or os.getenv('SCHOOLFLOW_WHATSAPP_ENABLED')=='1'):raise ValueError('Live WhatsApp integration is not enabled by the software owner. No provider request was sent.')
        p=current()
        if not p:raise ValueError('Select a saved provider first.')
        action=request.form.get('operation','')
        if action not in ('check_balance','account_stats','account_view','account_new','account_save','account_remove','account_rename','send','message_history'):raise ValueError('Choose a documented provider action.')
        fields={};data=state(p)
        if action in ('account_save','account_remove','account_rename'):
            remote_id=request.form.get('remote_id','').strip()
            if not re.fullmatch('[A-Za-z0-9_.:-]{1,100}',remote_id):raise ValueError('Use the provider account ID returned after QR linking.')
            fields['id']=remote_id
            if action=='account_save':fields.update(can_sync='1' if request.form.get('can_sync')=='1' else '0',can_inbox='1' if request.form.get('can_inbox')=='1' else '0')
            if action=='account_rename':
                name=request.form.get('remote_name','').strip()
                if not name or len(name)>120:raise ValueError('Use an account name up to 120 characters.')
                fields['name']=name
        if action=='send':
            if not (app.config.get('WHATSAPP_SEND_ENABLED') or os.getenv('SCHOOLFLOW_WHATSAPP_SEND_ENABLED')=='1'):raise ValueError('Message sending is not enabled. No message was sent.')
            device=request.form.get('device','');mobile=request.form.get('mobile','').strip();message=request.form.get('message','');media=request.form.get('media_url','').strip()
            if not any(str(x['id'])==device for x in linked(data)):raise ValueError('Choose a linked account from the current provider.')
            if not re.fullmatch('[1-9][0-9]{7,14}',mobile) or not message.strip() or len(message)>4096:raise ValueError('Use an international mobile number without + and a message up to 4,096 characters.')
            if media:
                url=urllib.parse.urlsplit(media)
                if url.scheme!='https' or not url.hostname or url.username or url.password or len(media)>1000:raise ValueError('Use a valid HTTPS media URL.')
                import ipaddress,socket
                try:
                    addresses=socket.getaddrinfo(url.hostname,443,type=socket.SOCK_STREAM)
                    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError()
                except Exception:raise ValueError('The media host must resolve to public addresses.') from None
            fields=dict(device=device,mobile=mobile,message=message,media_url=media)
        token=request.form.get('token','')
        if not re.fullmatch('[a-f0-9]{48}',token):raise ValueError('Reload this command form.')
        import hashlib
        fingerprint=hashlib.sha256(json.dumps(dict(provider=p.id,action=action,fields=fields),sort_keys=True).encode()).hexdigest();previous=Command.query.filter_by(token=token).first()
        if previous:
            if previous.fingerprint!=fingerprint:raise ValueError('This form token was used with different data.')
            flash('This command was already submitted. Review its result/provider history before sending again.','info');return redirect(url_for('whatsapp_settings.manager'))
        version(p)
        claim=Command(provider_id=p.id,token=token,action=action,fingerprint=fingerprint,status='Pending',payload=encrypt(fields));db.session.add(claim);db.session.flush();claim_id=claim.id;provider_id=p.id;secret=decrypt(p.secret);endpoint=p.endpoint
        # Commit the command claim before an external mutation. A timeout is
        # Unknown, never silently retried or reported as Sent/Delivered.
        commit()
        try:
            reply=provider_request(endpoint,secret,action,fields);reply=redacted(reply,secret)
            result='Failed' if isinstance(reply,dict) and (reply.get('success') is False or reply.get('error')) else 'Submitted'
        except ValueError:reply=None;result='Unknown'
        app.extensions['admission_capacity']['lock']();claim=db.session.get(Command,claim_id,populate_existing=True);p=db.session.get(Provider,provider_id,populate_existing=True)
        claim.status=result
        if reply is not None and p.active and action not in ('send','message_history'):
            data=state(p);data[action]=reply;p.state=encrypt(data)
        audit('WhatsApp provider command',provider_id=p.id,operation=action,outcome=result,command_id=claim_id);commit()
        if action=='message_history' and reply is not None:return render_template('whatsapp_remote_history.html',title='Provider Message History',response=reply)
        flash('Provider response received. Submitted does not confirm delivery.' if result=='Submitted' else 'Provider command '+result.lower()+'. Check the provider dashboard before repeating.','info');return redirect(url_for('whatsapp_settings.manager'))
    def cleanup():
        _,cfg=config();days=cfg['retention']
        if not days:return 0
        rows=Command.query.filter(Command.action=='send',Command.created<datetime.now(timezone.utc)-timedelta(days=days),Command.payload.isnot(None)).all()
        for row in rows:row.payload=None
        commit();return len(rows)
    import click
    @app.cli.command('whatsapp-history-prune')
    @click.option('--code',required=True)
    def prune_cli(code):
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code.upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        with app.test_request_context('/operator/whatsapp-retention'):
            g.institute_engine=engine
            try:click.echo(str(cleanup())+' expired message payloads removed.')
            finally:db.session.remove()
    app.extensions['whatsapp_helpers']=dict(cleanup=cleanup,encrypt=encrypt,decrypt=decrypt,config=config)
    app.register_blueprint(bp)
